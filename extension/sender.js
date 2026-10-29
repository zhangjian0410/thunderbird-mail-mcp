/* Thunderbird-facing boundary. This module never retries a send operation. */
(function (root) {
  'use strict';
  const normalizeId = value => String(value || '').replace(/^<|>$/g, '');
  const newlines = value => String(value).replace(/\r\n/g, '\n');
  const stable = value => JSON.stringify(value, function (_key, item) {
    return item && typeof item === 'object' && !Array.isArray(item)
      ? Object.fromEntries(Object.keys(item).sort().map(key => [key,item[key]])) : item;
  });
  const FAILURE_CODES = new Set([
    'forward_source_lookup','forward_raw_read','forward_native_compose',
    'forward_context','forward_body','forward_native_attachment',
    'forward_raw_mismatch','forward_caller_attachment','forward_final_guard'
  ]);
  const safeFailureCode = (value,fallback='forward_final_guard') =>
    FAILURE_CODES.has(value) ? value : (FAILURE_CODES.has(fallback) ? fallback : 'forward_final_guard');
  function sanitizeResult(result, fallback) {
    const clean = {...result};
    if (clean.status === 'failed' && clean.failure_code !== undefined) {
      clean.failure_code = safeFailureCode(clean.failure_code,fallback);
    } else if (clean.status !== 'failed') delete clean.failure_code;
    return clean;
  }
  async function atStage(code, action) {
    try {return await action();}
    catch (caught) {
      const error = caught && typeof caught === 'object' ? caught : new Error('Preparation failed');
      error.failure_code = safeFailureCode(error.failure_code,code);
      throw error;
    }
  }

  async function addresses(values, api) {
    const result = [];
    for (const value of values || []) {
      if (typeof value !== 'string') throw new Error('Non-mailbox recipient');
      const parsed = await api.messengerUtilities.parseMailboxString(value);
      if (!parsed.length || parsed.some(entry => !entry.email || entry.group)) throw new Error('Unresolved recipient');
      result.push(...parsed.map(entry => entry.email.toLowerCase()));
    }
    return result.sort();
  }

  async function sameRecipients(details, p, api) {
    for (const field of ['to','cc','bcc']) {
      if (stable(await addresses(details[field],api)) !== stable(p[field].map(a=>a.toLowerCase()).sort())) {
        throw new Error('Message recipients differ from authorized scope');
      }
    }
    if (details.newsgroups?.length || details.followupTo?.length) throw new Error('Non-email reply scope');
  }

  async function resolveOriginal(p, api) {
    const r = p.reply || p.forward;
    const matches = [];
    let page = await api.messages.query({headerMessageId:r.message_id,accountId:r.account_id,online:false});
    let pages = 0;
    while (true) {
      for (const message of page.messages) {
        if (normalizeId(message.headerMessageId) !== r.message_id || message.folder?.accountId !== r.account_id || message.external) {
          throw new Error('Original message/account mismatch');
        }
        matches.push(message);
      }
      if (matches.length > 1) throw new Error('Original message is ambiguous');
      if (!page.id) break;
      if (++pages > 1000) throw new Error('Original lookup did not complete');
      page = await api.messages.continueList(page.id);
    }
    if (matches.length !== 1) throw new Error('Original message not found');
    const message = await api.messages.get(matches[0].id);
    if (message.id !== matches[0].id || normalizeId(message.headerMessageId) !== r.message_id ||
        message.folder?.accountId !== r.account_id || message.external) throw new Error('Original changed');
    const full = await api.messages.getFull(message.id);
    const ids = full.headers?.['message-id'];
    if (!Array.isArray(ids) || ids.length !== 1 || normalizeId(ids[0]) !== r.message_id) throw new Error('Original Message-ID changed');
    // Ignore read/flag state. Bind MIME contents, stable headers and folder location.
    const {id,accountId,path} = message.folder;
    return {id:message.id,snapshot:stable({id:message.id,folder:{id,accountId,path},full})};
  }

  async function checkIdentity(p, api) {
    const source = p.reply || p.forward;
    const accounts = await api.accounts.list(false);
    const matches = accounts.flatMap(account => (account.identities || [])
      .filter(i => i.id === p.identity_id && i.email.toLowerCase() === p.from_email.toLowerCase())
      .map(identity => ({identity,account})));
    if (matches.length !== 1 || (source && matches[0].account.id !== p.identity_account_id)) {
      throw new Error('Sender identity/account changed');
    }
    if (source && accounts.filter(a=>a.id === source.account_id).length !== 1) throw new Error('Source account changed');
  }

  async function snapshotAttachments(tab, api) {
    const attached = await api.compose.listAttachments(tab.id);
    const result = [];
    for (const attachment of attached) {
      const file = await api.compose.getAttachmentFile(tab.id,attachment.id);
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),
        b=>b.toString(16).padStart(2,'0')).join('');
      result.push({name:attachment.name,size:attachment.size,sha256:hash});
    }
    return result;
  }

  async function snapshotForwardSource(original,api) {
    const file = await api.messages.getRaw(original.id,{data_format:'File'});
    if (!file || typeof file.arrayBuffer !== 'function') throw new Error('Forward source raw message unavailable');
    const bytes = await file.arrayBuffer();
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),
      b=>b.toString(16).padStart(2,'0')).join('');
    return {file,evidence:{size:bytes.byteLength,sha256:hash}};
  }

  function nativeForwardMetadata(attachment,source) {
    const classified=attachmentClass(attachment);
    if(classified.extension!=='.eml'||attachment.size!==source.size||
        !['message_rfc822','application_octet_stream','other'].includes(classified.type_class)) {
      const error=Error('Native forward attachment metadata changed');error.failure_code='forward_native_attachment';throw error;
    }
    if(!Number.isInteger(attachment.id)){
      const error=Error('Native forward attachment ID unavailable');error.failure_code='forward_native_attachment';throw error;
    }
    return {id:attachment.id,extension:classified.extension,size:attachment.size,type_class:classified.type_class};
  }

  async function checkForwardAttachments(tab,p,prepared,api) {
    const listed=await api.compose.listAttachments(tab.id),caller=p.attachments||[];
    if(listed.length!==1+caller.length) throw Error('Forward attachment count changed');
    if(stable(nativeForwardMetadata(listed[0],prepared.source))!==stable(prepared.native)) throw Error('Native attachment manifest changed');
    for(let i=0;i<caller.length;i++){
      const item=listed[i+1],expected=caller[i];
      if(item.name!==expected.name||item.size!==expected.size) throw Error('Caller attachment metadata changed');
      const file=await api.compose.getAttachmentFile(tab.id,item.id);
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('');
      if(hash!==expected.sha256) throw Error('Caller attachment bytes changed');
    }
  }

  function canonicalHtml(value) {
    return new DOMParser().parseFromString(newlines(value),'text/html').body.innerHTML;
  }

  async function checkCommon(tab,p,api,details) {
    await checkIdentity(p,api);
    details = details || await api.compose.getComposeDetails(tab.id);
    if (details.identityId !== p.identity_id) throw new Error('Native identity changed');
    const from = await addresses([details.from],api);
    if (stable(from) !== stable([p.from_email.toLowerCase()])) throw new Error('From changed');
    await sameRecipients(details,p,api);
    if (details.subject !== p.subject || details.attachVCard || details.attachPublicPGPKey) throw new Error('Message details changed');
    return details;
  }

  async function checkReply(tab, p, original, api, details) {
    const current = await resolveOriginal(p, api);
    if (current.snapshot !== original.snapshot) {
      const error = new Error('Original changed during preparation'); error.failure_code = 'forward_source_lookup'; throw error;
    }
    details = await checkCommon(tab,p,api,details);
    if (details.type !== 'reply' || details.relatedMessageId !== original.id || details.identityId !== p.identity_id) {
      throw new Error('Native reply context changed');
    }
    if (p.body_format === 'html') {
      if (details.isPlainText !== false || canonicalHtml(details.body) !== canonicalHtml(p.body)) throw new Error('HTML body changed');
    } else if (details.isPlainText !== true || newlines(details.plainTextBody) !== newlines(p.body)) {
      throw new Error('Plain text body changed');
    }
    const attached = await api.compose.listAttachments(tab.id);
    const expected = p.attachments || [];
    if (attached.length !== expected.length || attached.some((a,i)=>a.name !== expected[i].name || a.size !== expected[i].size)) {
      throw new Error('Attachments changed');
    }
    for (let i = 0; i < attached.length; i++) {
      const file = await api.compose.getAttachmentFile(tab.id,attached[i].id);
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('');
      if (hash !== expected[i].sha256) throw new Error('Attachment bytes changed');
    }
  }

  async function checkForward(tab,p,original,prepared,api,details) {
    const current = await atStage('forward_source_lookup',()=>resolveOriginal(p,api));
    if (current.snapshot !== original.snapshot) throw new Error('Original changed during preparation');
    const currentRaw = await atStage('forward_raw_read',()=>snapshotForwardSource(current,api));
    if (stable(currentRaw.evidence) !== stable(prepared.source)) {
      const error = new Error('Forward source changed during preparation'); error.failure_code = 'forward_raw_mismatch'; throw error;
    }
    details = await atStage('forward_context',()=>checkCommon(tab,p,api,details));
    if (details.type !== 'forward' || details.relatedMessageId !== original.id) {
      const error = new Error('Native forward context changed'); error.failure_code = 'forward_context'; throw error;
    }
    if (p.body_format === 'html') {
      if (details.isPlainText !== false || canonicalHtml(details.body) !== canonicalHtml(p.body)) {
        const error = new Error('HTML forward body changed'); error.failure_code = 'forward_body'; throw error;
      }
    } else if (details.isPlainText !== true || newlines(details.plainTextBody) !== newlines(p.body)) {
      const error = new Error('Plain text forward body changed'); error.failure_code = 'forward_body'; throw error;
    }
    await atStage('forward_native_attachment',()=>checkForwardAttachments(tab,p,prepared,api));
  }

  async function send(job, api, fetchAttachment) {
    const p = job.payload;
    if (p.body_format !== undefined && !['plain','html'].includes(p.body_format)) return {status:'failed',error:'Unsupported body format'};
    if (p.action && !['draft','send'].includes(p.action)) return {status:'failed',error:'Unsupported action'};
    if (p.reply && (!['reply_all','reply_sender'].includes(p.reply.mode) || p.reply.identity_id !== p.identity_id || p.action === 'draft')) {
      return {status:'failed',error:'Unsupported reply context'};
    }
    if (p.forward && (p.forward.mode !== 'forward_attachment' || p.forward.identity_id !== p.identity_id || p.action === 'draft' || p.reply)) {
      return {status:'failed',error:'Unsupported forward context'};
    }
    try {
      await checkIdentity(p,api);
    } catch (_) {
      return {status: 'failed', error: 'Cannot read sender identity; send was not attempted'};
    }
    let tab, original, prepared, guard, removedListener, bindCreatedTab, creationStarted = false;
    let failureCode = p.forward ? 'forward_source_lookup' : undefined;
    let allowSend = false, blocked = true, guardCancelled = false;
    const releaseGuard = () => {
      if (guard) api.compose.onBeforeSend.removeListener(guard);
      if (removedListener) api.tabs.onRemoved.removeListener(removedListener);
    };
    const closePrepared = async () => {
      // Revoke the one-use send permit BEFORE awaiting any window operation.
      blocked = true;
      allowSend = false;
      if (!tab) {
        bindCreatedTab?.(null);
        releaseGuard();
        return;
      }
      try {
        await api.tabs.remove(tab.id);
        releaseGuard();
      } catch (_) {
        // A failed close does not prove the composer is gone. Keep its exact-ID
        // guard until onRemoved confirms closure (or the extension stops).
      }
    };
    try {
      if (p.reply || p.forward) original = await atStage(failureCode || 'reply_source_lookup',()=>resolveOriginal(p,api));
      if (p.forward) failureCode = 'forward_raw_read';
      const forwardRaw = p.forward ? await atStage(failureCode,()=>snapshotForwardSource(original,api)) : null;
      const files = [];
      if (p.forward) failureCode = 'forward_caller_attachment';
      for (const meta of p.attachments || []) {
        if (!Number.isInteger(meta.size) || meta.size < 0 || meta.size > 20*1024*1024) throw new Error('Invalid attachment size');
        const bytes = new Uint8Array(meta.size);
        let offset = 0;
        do {
          const chunk = await fetchAttachment(job, meta.index, offset);
          const decoded = Uint8Array.from(atob(chunk.data_base64), c => c.charCodeAt(0));
          if (offset + decoded.length > bytes.length) throw new Error('Attachment overflow');
          bytes.set(decoded, offset);
          offset += decoded.length;
          if (chunk.next_offset === null) break;
          if (!decoded.length || chunk.next_offset !== offset) throw new Error('Attachment chunk mismatch');
        } while (offset < meta.size);
        const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), b=>b.toString(16).padStart(2,'0')).join('');
        if (offset !== meta.size || hash !== meta.sha256) throw new Error('Attachment content mismatch');
        files.push(new File([bytes], meta.name, {type:meta.type}));
      }
      const details = {
        identityId: p.identity_id, to: p.to, cc: p.cc, bcc: p.bcc,
        subject: p.subject,
        ...(p.body_format === 'html'
          ? {body: p.body, isPlainText: false, deliveryFormat: 'both'}
          : {plainTextBody: p.body, isPlainText: true, deliveryFormat: 'plaintext'})
      };
      if (p.reply || p.forward) {
        // Events raised before beginReply returns wait for its precise tab ID.
        // A reply to the same original in another manual window must pass.
        const createdTab = new Promise(resolve => {bindCreatedTab = resolve;});
        guard = async (sendingTab, eventDetails) => {
          if (!tab) {
            const created = await createdTab;
            return created && sendingTab.id === created.id ? {cancel:true} : undefined;
          }
          if (sendingTab.id !== tab.id) return undefined;
          if (blocked || !allowSend) return {cancel:true};
          allowSend = false;
          try {
            if (p.reply) await checkReply(tab,p,original,api,eventDetails);
            else await checkForward(tab,p,original,prepared,api,eventDetails);
            return blocked ? {cancel:true} : undefined;
          } catch (_) {
            guardCancelled = true;
            blocked = true;
            return {cancel:true};
          }
        };
        api.compose.onBeforeSend.addListener(guard);
        // Let Thunderbird create the native source-bound context first. Never use beginNew.
        creationStarted = true;
        if (p.forward) failureCode = 'forward_native_compose';
        tab = p.reply
          ? await api.compose.beginReply(original.id,
              p.reply.mode === 'reply_all' ? 'replyToAll' : 'replyToSender',
              {identityId:p.identity_id,isPlainText:p.body_format !== 'html'})
          : await api.compose.beginForward(original.id,'forwardAsAttachment',
              {identityId:p.identity_id,isPlainText:p.body_format !== 'html'});
        bindCreatedTab(tab);
        if (api.tabs.onRemoved) {
          removedListener = removedId => {if (removedId === tab.id) releaseGuard();};
          api.tabs.onRemoved.addListener(removedListener);
        }
        const native = await api.compose.getComposeDetails(tab.id);
        if (p.reply) {
          if (native.type !== 'reply' || native.relatedMessageId !== original.id || native.identityId !== p.identity_id) throw new Error('Not a native reply');
          await sameRecipients(native,p,api);
          // Replace auto quote/signature and remove inherited inline attachments.
          for (const attachment of await api.compose.listAttachments(tab.id)) await api.compose.removeAttachment(tab.id,attachment.id);
          await api.compose.setComposeDetails(tab.id,{...details,attachVCard:false,attachPublicPGPKey:false});
        } else {
          failureCode = 'forward_context';
          if (native.type !== 'forward' || native.relatedMessageId !== original.id || native.identityId !== p.identity_id) throw new Error('Not a native forward');
          failureCode = 'forward_native_attachment';
          const inherited = await api.compose.listAttachments(tab.id);
          if(inherited.length!==1)throw new Error('Native forward attachment count changed');
          const nativeManifest=nativeForwardMetadata(inherited[0],forwardRaw.evidence);
          failureCode = 'forward_body';
          await api.compose.setComposeDetails(tab.id,{...details,attachVCard:false,attachPublicPGPKey:false});
          prepared = {source:forwardRaw.evidence,native:nativeManifest};
        }
      } else {
        tab = await api.compose.beginNew(details);
      }
      if (p.forward) failureCode = 'forward_caller_attachment';
      for (const file of files) await api.compose.addAttachment(tab.id, {file});
      if (files.length && !p.forward) {
        const attached = await api.compose.listAttachments(tab.id);
        if (attached.length !== files.length || attached.some((a,i)=>a.name !== files[i].name || a.size !== files[i].size)) throw new Error('Attachment list mismatch');
      }
      if (p.reply) await checkReply(tab,p,original,api);
      if (p.forward) {failureCode = 'forward_final_guard'; await checkForward(tab,p,original,prepared,api);}
    } catch (error) {
      await closePrepared();
      if ((p.reply || p.forward) && creationStarted && !tab) {
        const kind = p.reply ? 'reply' : 'forward';
        return {status:'failed',error:`Native ${kind} creation failed without a precise composer ID; no send was called and no body was set; an unidentified native window cannot be correlated safely`,
          ...(p.forward ? {failure_code:safeFailureCode(error.failure_code,failureCode || 'forward_native_compose')} : {})};
      }
      return {status: 'failed', error: 'Cannot prepare message; send was not attempted',
        ...(p.forward ? {failure_code:safeFailureCode(error.failure_code,failureCode || 'forward_final_guard')} : {})};
    }
    if (p.action === 'draft') {
      try {
        const saved = await api.compose.saveMessage(tab.id, {mode:'draft'});
        if (saved.mode !== 'draft' || !saved.messages?.length) throw new Error('Draft not confirmed');
        const drafts = saved.messages.map(({id,headerMessageId,folder})=>({id,headerMessageId,folder}));
        try {await api.tabs.remove(tab.id);} catch (_) {}
        return {status:'drafted',drafts};
      } catch (_) {return {status:'unknown',error:'Draft save outcome unknown; no send was attempted; inspect drafts before repeating'};}
    }
    let outcome;
    try {
      blocked = false;
      allowSend = true;
      // Deliberately inherit the selected identity's FCC settings.
      outcome = await api.compose.sendMessage(tab.id, {mode: 'sendNow'});
    } catch (error) {
      if (guardCancelled) {
        return {status:'failed',error:'Source-bound message changed before sending; send cancelled',
          ...(p.forward ? {failure_code:'forward_final_guard'} : {})};
      }
      return {status: 'unknown', error: `Send API did not confirm delivery; do not resend: ${String(error.message || error).slice(0, 1000)}`};
    } finally {
      // This also covers cancellation, API rejection and unconfirmed outcomes.
      // Never leave a live failed/unknown composer with a send-capable guard.
      if (p.reply || p.forward) await closePrepared();
    }
    if (outcome.mode !== 'sendNow' || !outcome.headerMessageId) {
      return {status: 'unknown', error: 'No immediate-send Message-ID confirmation; do not resend'};
    }
    const copies = [];
    for (const copy of outcome.messages || []) {
      try {
        const saved = await api.messages.get(copy.id);
        if (normalizeId(saved.headerMessageId) === normalizeId(outcome.headerMessageId) && saved.folder) {
          const {id, accountId, path, name} = saved.folder;
          copies.push({id: saved.id, folder: {id, accountId, path, name}});
        }
      } catch (_) { /* Delivery remains successful even if FCC verification fails. */ }
    }
    return {status: 'sent', message_id: outcome.headerMessageId,
      copy_status: copies.length ? 'verified' : 'not_verified', copies};
  }

  async function execute(job, api, report, fetchAttachment) {
    const key = `pending:${job.request_id}`;
    const record = {request_id: job.request_id, claim_token: job.claim_token};
    // Persist before touching SMTP. Recovery of an unfinished send only reports unknown.
    await api.storage.local.set({[key]: record});
    record.result = sanitizeResult(await send(job, api, fetchAttachment));
    await api.storage.local.set({[key]: record});
    await report(record.request_id, record.claim_token, record.result);
    await api.storage.local.remove(key);
  }

  async function recover(api, report) {
    const records = await api.storage.local.get(null);
    for (const [key, record] of Object.entries(records)) {
      if (!key.startsWith('pending:')) continue;
      const result = record.result
        ? sanitizeResult(record.result,'forward_final_guard')
        : {status:'unknown', error:'Extension restarted during send; do not resend'};
      await report(record.request_id, record.claim_token, result);
      await api.storage.local.remove(key);
    }
  }

  const mimeClass = value => value === 'message/rfc822' ? 'message_rfc822'
    : value === 'application/octet-stream' ? 'application_octet_stream'
    : String(value || '').startsWith('text/') ? 'text' : 'other';
  const attachmentClass = item => {
    const match = String(item.name || '').toLowerCase().match(/(\.[a-z0-9]{1,10})$/);
    return {extension:match ? match[1] : null,type_class:mimeClass(item.type),
      ...(Number.isInteger(item.size)&&item.size>=0?{metadata_size:item.size}:{})};
  };
  const DIAGNOSTIC_ITEM_LIMIT = 16;
  const attachmentSummary = items => ({count:items.length,
    truncated:items.length>DIAGNOSTIC_ITEM_LIMIT,
    items:items.slice(0,DIAGNOSTIC_ITEM_LIMIT).map(attachmentClass)});

  async function diagnoseForward(job,api) {
    const p=job.payload; let tab,guard,removedListener,bindCreatedTab; let stage='forward_source_lookup';
    const result={status:'failed',failure_stage:stage};
    try {
      await checkIdentity(p,api);
      const original=await atStage(stage,()=>resolveOriginal(p,api));
      stage='forward_raw_read';
      const raw=await atStage(stage,()=>snapshotForwardSource(original,api));
      Object.assign(result,{source_size:raw.evidence.size,source_sha256:raw.evidence.sha256});
      stage='forward_native_compose';
      const createdTab=new Promise(resolve=>{bindCreatedTab=resolve;});
      guard=async sendingTab=>{const target=tab||await createdTab;return target&&sendingTab.id===target.id?{cancel:true}:undefined;};
      api.compose.onBeforeSend.addListener(guard);
      tab=await api.compose.beginForward(original.id,'forwardAsAttachment',
        {identityId:p.identity_id,isPlainText:p.body_format!=='html'});
      bindCreatedTab(tab);
      if(api.tabs.onRemoved){removedListener=removedId=>{if(removedId===tab.id){api.compose.onBeforeSend.removeListener(guard);api.tabs.onRemoved.removeListener(removedListener);}};api.tabs.onRemoved.addListener(removedListener);}
      stage='forward_context';
      const details=await api.compose.getComposeDetails(tab.id);
      if(details.type!=='forward'||details.relatedMessageId!==original.id||details.identityId!==p.identity_id) throw Error('context');
      stage='forward_native_attachment';
      const inherited=await api.compose.listAttachments(tab.id);
      result.inherited=attachmentSummary(inherited);
      for(const item of [...inherited].reverse()) await api.compose.removeAttachment(tab.id,item.id);
      if((await api.compose.listAttachments(tab.id)).length) throw Error('clear');
      await api.compose.addAttachment(tab.id,{file:raw.file});
      stage='reread_list';
      const listed=await api.compose.listAttachments(tab.id);
      result.reread={...attachmentSummary(listed),size:null,sha256:null,equal:false};
      if(listed.length!==1){stage='reread_compare';throw Error('mismatch');}
      stage='reread_get_file';
      const rereadFile=await api.compose.getAttachmentFile(tab.id,listed[0].id);
      stage='reread_array_buffer';
      const rereadBytes=await rereadFile.arrayBuffer();result.reread.size=rereadBytes.byteLength;
      stage='reread_hash';
      const digest=api.cryptoDigest?await api.cryptoDigest('SHA-256',rereadBytes):await crypto.subtle.digest('SHA-256',rereadBytes);
      result.reread.sha256=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
      stage='reread_compare';
      result.reread.equal=result.reread.size===raw.evidence.size&&result.reread.sha256===raw.evidence.sha256;
      if(!result.reread.equal) throw Error('mismatch');
      result.status='prepared'; delete result.failure_stage;
    } catch (_) {result.failure_stage=stage;}
    finally {
      if(!tab){bindCreatedTab?.(null);if(guard)api.compose.onBeforeSend.removeListener(guard);}
      else try{await api.tabs.remove(tab.id);result.close_confirmed=true;if(guard)api.compose.onBeforeSend.removeListener(guard);if(removedListener)api.tabs.onRemoved.removeListener(removedListener);}
      catch(_){result.status='failed';result.failure_stage='close_not_confirmed';result.close_confirmed=false;}
    }
    if(result.close_confirmed===undefined) result.close_confirmed=false;
    return result;
  }

  const exported = {send, execute, recover, diagnoseForward};
  root.NativeSendCore = exported;
  if (typeof module !== 'undefined') module.exports = exported;
})(globalThis);
