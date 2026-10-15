/* Thunderbird-facing boundary. This module never retries a send operation. */
(function (root) {
  'use strict';
  const normalizeId = value => String(value || '').replace(/^<|>$/g, '');

  async function send(job, api, fetchAttachment) {
    const p = job.payload;
    if (p.body_format !== undefined && !['plain','html'].includes(p.body_format)) return {status:'failed',error:'Unsupported body format'};
    if (p.action && !['draft','send'].includes(p.action)) return {status:'failed',error:'Unsupported action'};
    let identities;
    try {
      identities = (await api.accounts.list(false)).flatMap(a => a.identities || []);
    } catch (_) {
      return {status: 'failed', error: 'Cannot read sender identity; send was not attempted'};
    }
    if (!identities.some(i => i.id === p.identity_id && i.email.toLowerCase() === p.from_email.toLowerCase())) {
      return {status: 'failed', error: 'Sender identity changed; send was not attempted'};
    }
    let tab;
    try {
      const files = [];
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
      tab = await api.compose.beginNew({
        identityId: p.identity_id, to: p.to, cc: p.cc, bcc: p.bcc,
        subject: p.subject,
        ...(p.body_format === 'html'
          ? {body: p.body, isPlainText: false, deliveryFormat: 'both'}
          : {plainTextBody: p.body, isPlainText: true, deliveryFormat: 'plaintext'})
      });
      for (const file of files) await api.compose.addAttachment(tab.id, {file});
      if (files.length) {
        const attached = await api.compose.listAttachments(tab.id);
        if (attached.length !== files.length || attached.some((a,i)=>a.name !== files[i].name || a.size !== files[i].size)) throw new Error('Attachment list mismatch');
      }
    } catch (_) {
      if (tab) {try {await api.tabs.remove(tab.id);} catch (_) {}}
      return {status: 'failed', error: 'Cannot prepare message; send was not attempted'};
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
      // Deliberately inherit the selected identity's FCC settings.
      outcome = await api.compose.sendMessage(tab.id, {mode: 'sendNow'});
    } catch (error) {
      return {status: 'unknown', error: `Send API did not confirm delivery; do not resend: ${String(error.message || error).slice(0, 1000)}`};
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
    record.result = await send(job, api, fetchAttachment);
    await api.storage.local.set({[key]: record});
    await report(record.request_id, record.claim_token, record.result);
    await api.storage.local.remove(key);
  }

  async function recover(api, report) {
    const records = await api.storage.local.get(null);
    for (const [key, record] of Object.entries(records)) {
      if (!key.startsWith('pending:')) continue;
      const result = record.result || {status:'unknown', error:'Extension restarted during send; do not resend'};
      await report(record.request_id, record.claim_token, result);
      await api.storage.local.remove(key);
    }
  }

  const exported = {send, execute, recover};
  root.NativeSendCore = exported;
  if (typeof module !== 'undefined') module.exports = exported;
})(globalThis);
