const {test} = require('node:test');
const assert = require('node:assert/strict');
const {webcrypto,createHash} = require('node:crypto');
globalThis.crypto = webcrypto;
const core = require('../extension/sender.js');

function fixture(format='plain') {
  const job={request_id:'forward',claim_token:'token',payload:{
    identity_id:'id1',identity_account_id:'account1',from_email:'sender@example.com',
    to:['one@example.com'],cc:['copy@example.com'],bcc:[],subject:'Fwd: approved',
    body:format === 'html' ? '<p>Approved commentary</p>' : 'Approved commentary',
    ...(format === 'html' ? {body_format:'html'} : {}),
    forward:{message_id:'original@example.test',account_id:'source1',identity_id:'id1',mode:'forward_attachment'}
  }};
  const original={id:3,headerMessageId:'original@example.test',external:false,
    folder:{id:'source1://Inbox',accountId:'source1',path:'/Inbox'}};
  const full={headers:{'message-id':['<original@example.test>']},body:'Original source'};
  const rawBytes='From: source@example.test\r\nMessage-ID: <original@example.test>\r\n\r\nOriginal source';
  const inherited=new File([rawBytes],'original.eml',{type:'message/rfc822'});
  const attached=[inherited], records={}, guards=new Set(), removedListeners=new Set();
  const calls={new:0,forward:[],send:0,delivered:0,removed:0,queries:0};
  let details;
  const api={
    accounts:{list:async()=>[{id:'account1',identities:[{id:'id1',email:'sender@example.com'}]},
                             {id:'source1',identities:[]}]},
    messengerUtilities:{parseMailboxString:async value=>value.split(',').map(v=>({email:(v.match(/<([^>]+)>/)?.[1]||v.trim())}))},
    storage:{local:{get:async()=>structuredClone(records),set:async data=>Object.assign(records,structuredClone(data)),remove:async key=>delete records[key]}},
    messages:{
      query:async query=>{calls.queries++;assert.deepEqual(query,{headerMessageId:'original@example.test',accountId:'source1',online:false});return {messages:[structuredClone(original)],id:null};},
      get:async id=>id===3?structuredClone(original):({id,headerMessageId:'out@example.test',folder:{accountId:'account1',path:'/Sent'}}),
      getFull:async()=>structuredClone(full),
      getRaw:async(id,options)=>{assert.equal(id,3);assert.deepEqual(options,{data_format:'File'});
        return new File([rawBytes],'source.eml',{type:'message/rfc822'});}
    },
    compose:{
      beginNew:async()=>{calls.new++;throw Error('must never begin new');},
      beginReply:async()=>{throw Error('must never reply');},
      beginForward:async(...args)=>{calls.forward.push(args);details={identityId:'id1',type:'forward',relatedMessageId:3,
        from:'Sender <sender@example.com>',to:[],cc:[],bcc:[],newsgroups:[],followupTo:[],subject:'Fwd: original',
        ...(format==='html'?{body:'<p>native signature</p>',isPlainText:false}:
          {plainTextBody:'native signature',isPlainText:true})};return {id:7};},
      getComposeDetails:async()=>structuredClone(details),
      setComposeDetails:async(_id,changes)=>Object.assign(details,structuredClone(changes)),
      listAttachments:async()=>attached.map((file,id)=>({id,name:file.name,size:file.size})),
      getAttachmentFile:async(_id,id)=>attached[id],
      addAttachment:async(_id,{file})=>{attached.push(file);return {id:attached.length-1};},
      removeAttachment:async(_id,id)=>attached.splice(id,1),
      onBeforeSend:{addListener:fn=>guards.add(fn),removeListener:fn=>guards.delete(fn)},
      saveMessage:async()=>{throw Error('must never draft');},
      sendMessage:async(tabId,options)=>{calls.send++;assert.deepEqual(options,{mode:'sendNow'});
        for (const guard of guards) if ((await guard({id:tabId},structuredClone(details)))?.cancel) throw Error('cancelled');
        calls.delivered++;return {mode:'sendNow',headerMessageId:'out@example.test',messages:[{id:42}]};}
    },
    tabs:{remove:async()=>calls.removed++,onRemoved:{addListener:fn=>removedListeners.add(fn),removeListener:fn=>removedListeners.delete(fn)}}
  };
  return {job,api,calls,original,full,rawBytes,attached,records,guards,removedListeners,details:()=>details};
}

test('native attachment forward sets exact approved plain body and preserves raw original message',async()=>{
  const f=fixture();
  const result=await core.send(f.job,f.api);
  assert.equal(result.status,'sent');assert.equal(result.copy_status,'verified');
  assert.deepEqual(f.calls.forward,[[3,'forwardAsAttachment',{identityId:'id1',isPlainText:true}]]);
  assert.equal(f.calls.new,0);assert.equal(f.calls.delivered,1);
  assert.equal(f.details().plainTextBody,'Approved commentary');
  assert.equal(f.attached.length,1);assert.equal(f.attached[0].name,'original.eml');
  assert.equal(await f.attached[0].text(),f.rawBytes);
  assert.ok(f.calls.queries>=3);assert.equal(f.guards.size,0);
});

test('HTML native attachment forward sets exact approved HTML body',async()=>{
  const previous=globalThis.DOMParser;
  globalThis.DOMParser=class{parseFromString(value){return{body:{innerHTML:value,textContent:String(value).replace(/<[^>]*>/g,'')}};}};
  try {
    const f=fixture('html');
    assert.equal((await core.send(f.job,f.api)).status,'sent');
    assert.equal(f.details().body,'<p>Approved commentary</p>');
    assert.equal(f.details().deliveryFormat,'both');
  } finally {if(previous===undefined)delete globalThis.DOMParser;else globalThis.DOMParser=previous;}
});

test('caller attachment is appended while native attachment is preserved and both bytes are guarded',async()=>{
  const f=fixture(),bytes=Buffer.from('approved new attachment');
  f.job.payload.attachments=[{index:0,name:'approved.txt',size:bytes.length,type:'text/plain',
    sha256:createHash('sha256').update(bytes).digest('hex')}];
  const result=await core.send(f.job,f.api,async()=>({data_base64:bytes.toString('base64'),next_offset:null}));
  assert.equal(result.status,'sent');assert.deepEqual(f.attached.map(a=>a.name),['original.eml','approved.txt']);
});

test('caller attachment byte mutation still fails without reading native eml bytes',async()=>{
  const f=fixture(),bytes=Buffer.from('approved new attachment');
  f.job.payload.attachments=[{index:0,name:'approved.txt',size:bytes.length,type:'text/plain',sha256:createHash('sha256').update(bytes).digest('hex')}];
  const add=f.api.compose.addAttachment;f.api.compose.addAttachment=async(...args)=>{const value=await add(...args);f.attached[1]=new File(['x'.repeat(bytes.length)],'approved.txt');return value;};
  assert.equal((await core.send(f.job,f.api,async()=>({data_base64:bytes.toString('base64'),next_offset:null}))).status,'failed');
  assert.equal(f.calls.delivered,0);
});

test('pre-first-snapshot body replacement is overwritten with exact approved commentary',async()=>{
  const f=fixture(),begin=f.api.compose.beginForward;
  f.api.compose.beginForward=async(...args)=>{const tab=await begin(...args);f.details().plainTextBody='Attacker replacement';return tab;};
  assert.equal((await core.send(f.job,f.api)).status,'sent');
  assert.equal(f.details().plainTextBody,'Approved commentary');assert.equal(f.calls.delivered,1);
});

test('missing native inline header is irrelevant because attachment mode controls the exact body',async()=>{
  const f=fixture(),begin=f.api.compose.beginForward;
  f.api.compose.beginForward=async(...args)=>{const tab=await begin(...args);f.details().plainTextBody='';return tab;};
  assert.equal((await core.send(f.job,f.api)).status,'sent');
  assert.equal(f.details().plainTextBody,'Approved commentary');
});

test('native attachment removal fails closed',async()=>{
  const f=fixture(),begin=f.api.compose.beginForward;
  f.api.compose.beginForward=async(...args)=>{const tab=await begin(...args);f.attached.splice(0);return tab;};
  assert.equal((await core.send(f.job,f.api)).status,'failed');assert.equal(f.calls.delivered,0);
});

test('extra native attachment fails closed',async()=>{
  const f=fixture(),begin=f.api.compose.beginForward;
  f.api.compose.beginForward=async(...args)=>{const tab=await begin(...args);f.attached.push(new File(['extra'],'extra.txt'));return tab;};
  assert.equal((await core.send(f.job,f.api)).status,'failed');assert.equal(f.calls.delivered,0);
});

test('native attachment extension or size mutation fails closed',async()=>{
  const f=fixture(),begin=f.api.compose.beginForward;
  f.api.compose.beginForward=async(...args)=>{const tab=await begin(...args);
    f.attached[0]=new File(['mutated raw message'],'original.eml',{type:'message/rfc822'});return tab;};
  assert.equal((await core.send(f.job,f.api)).status,'failed');assert.equal(f.calls.delivered,0);
});

test('native eml getAttachmentFile may fail while stable metadata still sends',async()=>{
  const f=fixture();f.api.compose.getAttachmentFile=async()=>{throw Error('Thunderbird cannot expose native eml');};
  assert.equal((await core.send(f.job,f.api)).status,'sent');
  assert.equal(f.calls.delivered,1);
});

test('native eml remove-and-replace with same metadata but different ID is cancelled',async()=>{
  const f=fixture();let nativeId=11;
  f.api.compose.listAttachments=async()=>f.attached.map((file,index)=>({id:index?87:nativeId,name:file.name,size:file.size}));
  const set=f.api.compose.setComposeDetails;f.api.compose.setComposeDetails=async(...args)=>{await set(...args);
    f.attached[0]=new File(['x'.repeat(f.rawBytes.length)],'original.eml',{type:'message/rfc822'});nativeId=44;};
  const result=await core.send(f.job,f.api);
  assert.equal(result.status,'failed');assert.equal(f.calls.delivered,0);
});

test('caller attachment non-contiguous IDs use actual list mapping for byte verification',async()=>{
  const f=fixture(),bytes=Buffer.from('approved new attachment');
  f.job.payload.attachments=[{index:0,name:'approved.txt',size:bytes.length,type:'text/plain',sha256:createHash('sha256').update(bytes).digest('hex')}];
  f.api.compose.listAttachments=async()=>f.attached.map((file,index)=>({id:index?87:11,name:file.name,size:file.size}));
  f.api.compose.getAttachmentFile=async(_tab,id)=>{if(id===11)throw Error('native eml unreadable');if(id===87)return f.attached[1];throw Error('wrong id');};
  assert.equal((await core.send(f.job,f.api,async()=>({data_base64:bytes.toString('base64'),next_offset:null}))).status,'sent');
  assert.equal(f.calls.delivered,1);
});

test('source, native context, body, recipient, subject and inherited attachment mutations cancel before delivery',async()=>{
  for(const variant of ['source','type','related','body','recipient','subject','attachment']){
    const f=fixture(),set=f.api.compose.setComposeDetails;
    f.api.compose.setComposeDetails=async(...args)=>{await set(...args);
      if(variant==='source')f.full.body='changed source';
      if(variant==='type')f.details().type='new';
      if(variant==='related')f.details().relatedMessageId=99;
      if(variant==='body')f.details().plainTextBody+=' changed';
      if(variant==='recipient')f.details().bcc=['hidden@example.com'];
      if(variant==='subject')f.details().subject='changed';
      if(variant==='attachment')f.attached[0]=new File(['tampered attachment'],'source.eml',{type:'message/rfc822'});
    };
    assert.equal((await core.send(f.job,f.api)).status,'failed',variant);
    assert.equal(f.calls.delivered,0,variant);assert.equal(f.calls.new,0,variant);
  }
});

test('forward preparation failures expose bounded non-sensitive stage codes',async()=>{
  const cases=[
    ['forward_source_lookup',f=>{f.api.messages.query=async()=>({messages:[]});}],
    ['forward_raw_read',f=>{f.api.messages.getRaw=async()=>{throw Error('private path must not escape');};}],
    ['forward_native_compose',f=>{f.api.compose.beginForward=async()=>{throw Error('private compose detail');};}],
    ['forward_context',f=>{const begin=f.api.compose.beginForward;f.api.compose.beginForward=async(...a)=>{const t=await begin(...a);f.details().type='new';return t;};}],
    ['forward_native_attachment',f=>{f.attached[0]=new File([f.rawBytes],'private.txt');}],
    ['forward_raw_mismatch',f=>{let calls=0;f.api.messages.getRaw=async()=>new File([++calls===1?f.rawBytes:'changed raw'],'source.eml');}],
    ['forward_body',f=>{const set=f.api.compose.setComposeDetails;f.api.compose.setComposeDetails=async(...a)=>{await set(...a);f.details().plainTextBody='changed';};}],
    ['forward_caller_attachment',f=>{f.job.payload.attachments=[{index:0,name:'x',size:1,type:'text/plain',sha256:'0'.repeat(64)}];}],
    ['forward_final_guard',f=>{f.api.compose.sendMessage=async(tabId)=>{f.details().subject='changed';
      for(const guard of f.guards) if((await guard({id:tabId},structuredClone(f.details())))?.cancel) throw Error('cancelled');
      throw Error('guard failed to cancel');};}],
  ];
  for(const [code,mutate] of cases){const f=fixture();mutate(f);
    const result=await core.send(f.job,f.api,async()=>{throw Error('private caller path');});
    assert.equal(result.status,'failed',code);assert.equal(result.failure_code,code,JSON.stringify(result));
    assert.doesNotMatch(JSON.stringify(result),/private|attachment name|caller path/,code);
  }
});

test('malicious exception failure_code is normalized before return, storage and recovery',async()=>{
  const f=fixture(),writes=[],reports=[];
  f.api.messages.getRaw=async()=>{const error=Error('secret must not escape');error.failure_code='/private/mail/secret.eml';throw error;};
  f.api.storage.local.set=async data=>{writes.push(structuredClone(data));Object.assign(f.records,structuredClone(data));};
  await core.execute(f.job,f.api,async(_id,_token,result)=>reports.push(structuredClone(result)));
  const serialized=JSON.stringify({writes,reports});
  assert.doesNotMatch(serialized,/\/private\/mail\/secret\.eml|secret must not escape/);
  assert.equal(reports[0].failure_code,'forward_raw_read');
  assert.equal(f.calls.delivered,0);

  f.records['pending:hostile']={request_id:'hostile',claim_token:'token',
    result:{status:'failed',error:'safe generic error',failure_code:'/private/mail/secret.eml'}};
  const recovered=[];
  await core.recover(f.api,async(_id,_token,result)=>recovered.push(result));
  assert.equal(recovered[0].failure_code,'forward_final_guard');
  assert.doesNotMatch(JSON.stringify(recovered),/\/private\/mail\/secret\.eml/);
});

test('prepare-only diagnostic walks native replacement path, closes exact tab and never sends or saves',async()=>{
  const f=fixture();f.attached[0]=new File(['Thunderbird reserialized bytes'],'private-customer-name.eml',{type:'message/rfc822'});
  let saves=0;f.api.compose.saveMessage=async()=>{saves++;throw Error('must not save');};
  const result=await core.diagnoseForward(f.job,f.api);
  assert.equal(result.status,'prepared');assert.equal(result.reread.equal,true);
  assert.equal(result.source_sha256,createHash('sha256').update(f.rawBytes).digest('hex'));
  assert.equal(result.reread.sha256,result.source_sha256);assert.equal(result.close_confirmed,true);
  assert.deepEqual(result.inherited.items,[{extension:'.eml',type_class:'other',metadata_size:30}]);
  assert.doesNotMatch(JSON.stringify(result),/private-customer-name|Original source|sender@example/);
  assert.equal(f.calls.send,0);assert.equal(f.calls.delivered,0);assert.equal(saves,0);assert.equal(f.calls.removed,1);
});

test('prepare-only diagnostic bounds attachment classifications',async()=>{
  const f=fixture();
  f.attached.splice(0,1,...Array.from({length:2500},(_,index)=>
    new File(['x'],`private-${index}.eml`,{type:'message/rfc822'})));
  const result=await core.diagnoseForward(f.job,f.api);
  assert.equal(result.status,'prepared');assert.equal(result.inherited.count,2500);
  assert.equal(result.inherited.truncated,true);assert.equal(result.inherited.items.length,16);
  assert.ok(Buffer.byteLength(JSON.stringify(result))<16*1024);
  assert.doesNotMatch(JSON.stringify(result),/private-/);
  assert.equal(f.calls.send,0);assert.equal(f.calls.delivered,0);assert.equal(f.calls.removed,1);
});

test('prepare-only diagnostic blocks send throughout and close failure stays failed with guard retained',async()=>{
  const f=fixture();let pendingGuard;const begin=f.api.compose.beginForward;
  f.api.compose.beginForward=async(...args)=>{for(const guard of f.guards)pendingGuard=guard({id:7});return begin(...args);};
  f.api.tabs.remove=async()=>{throw Error('close failed');};
  const result=await core.diagnoseForward(f.job,f.api);
  assert.equal((await pendingGuard)?.cancel,true);assert.equal(result.status,'failed');
  assert.equal(result.failure_stage,'close_not_confirmed');assert.equal(result.close_confirmed,false);
  assert.equal(f.guards.size,1);assert.deepEqual(await [...f.guards][0]({id:7}),{cancel:true});
  assert.equal(f.calls.send,0);assert.equal(f.calls.delivered,0);
});

test('prepare-only diagnostic reports reread mismatch without sending',async()=>{
  const f=fixture(),add=f.api.compose.addAttachment;
  f.api.compose.addAttachment=async(...args)=>{const value=await add(...args);f.attached[0]=new File(['changed'],'source.eml',{type:'message/rfc822'});return value;};
  const result=await core.diagnoseForward(f.job,f.api);
  assert.equal(result.status,'failed');assert.equal(result.failure_stage,'reread_compare');
  assert.equal(result.reread.equal,false);assert.equal(result.close_confirmed,true);
  assert.equal(f.calls.send,0);assert.equal(f.calls.delivered,0);
});

test('prepare-only reread failures expose fixed stages and retain safe partial metadata',async()=>{
  for(const variant of ['reread_list','reread_get_file','reread_array_buffer','reread_hash']){
    const f=fixture();let saves=0;f.api.compose.saveMessage=async()=>{saves++;};
    if(variant==='reread_list'){const list=f.api.compose.listAttachments;let calls=0;f.api.compose.listAttachments=async(...a)=>{if(++calls===3)throw Error('/private/list');return list(...a);};}
    if(variant==='reread_get_file')f.api.compose.getAttachmentFile=async()=>{throw Error('/private/file');};
    if(variant==='reread_array_buffer')f.api.compose.getAttachmentFile=async()=>({arrayBuffer:async()=>{throw Error('/private/buffer');}});
    if(variant==='reread_hash')f.api.cryptoDigest=async()=>{throw Error('/private/hash');};
    const result=await core.diagnoseForward(f.job,f.api);
    assert.equal(result.status,'failed',variant);assert.equal(result.failure_stage,variant);assert.equal(result.close_confirmed,true);
    if(variant!=='reread_list'){assert.equal(result.reread.count,1);assert.equal(result.reread.items[0].extension,'.eml');assert.ok(result.reread.items[0].metadata_size>0);}
    assert.doesNotMatch(JSON.stringify(result),/\/private\//);assert.equal(f.calls.send,0);assert.equal(f.calls.delivered,0);assert.equal(saves,0);assert.equal(f.calls.removed,1);
  }
});

test('missing, ambiguous, wrong-account and external originals fail without any compose or send',async()=>{
  for(const variant of ['missing','ambiguous','wrong-account','external']){
    const f=fixture();
    if(variant==='missing')f.api.messages.query=async()=>({messages:[]});
    if(variant==='ambiguous')f.api.messages.query=async()=>({messages:[f.original,{...f.original,id:4}]});
    if(variant==='wrong-account')f.original.folder.accountId='other';
    if(variant==='external')f.original.external=true;
    assert.equal((await core.send(f.job,f.api)).status,'failed',variant);
    assert.equal(f.calls.forward.length,0,variant);assert.equal(f.calls.send,0,variant);assert.equal(f.calls.new,0,variant);
  }
});

test('unsupported mode and native creation rejection never fall back to beginNew',async()=>{
  const unsupported=fixture();unsupported.job.payload.forward.mode='forward_inline';
  assert.equal((await core.send(unsupported.job,unsupported.api)).status,'failed');
  assert.equal(unsupported.calls.forward.length,0);assert.equal(unsupported.calls.new,0);
  const rejected=fixture();rejected.api.compose.beginForward=async()=>{throw Error('native rejected');};
  const result=await core.send(rejected.job,rejected.api);
  assert.equal(result.status,'failed');assert.match(result.error,/without a precise composer ID/);
  assert.equal(rejected.calls.new,0);assert.equal(rejected.calls.send,0);
});

test('manual or unrelated forward windows are unaffected and exact target is guarded once',async()=>{
  const f=fixture();
  f.api.compose.sendMessage=async()=>{f.calls.send++;
    for(const guard of f.guards){
      assert.equal(await guard({id:8},f.details()),undefined);
      const first=guard({id:7},f.details()),second=guard({id:7},f.details());
      assert.equal(await first,undefined);assert.deepEqual(await second,{cancel:true});
    }
    f.calls.delivered++;return{mode:'sendNow',headerMessageId:'out@example.test',messages:[]};
  };
  assert.equal((await core.send(f.job,f.api)).status,'sent');assert.equal(f.calls.delivered,1);
});
