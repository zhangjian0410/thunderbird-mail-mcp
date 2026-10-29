const {test} = require('node:test');
const assert = require('node:assert/strict');
const {webcrypto,createHash} = require('node:crypto');
globalThis.crypto = webcrypto;
const core = require('../extension/sender.js');

function fixture(mode='reply_all') {
  const job = {request_id:'reply',claim_token:'token',payload:{
    identity_id:'id1',identity_account_id:'account1',from_email:'sender@example.com',
    to:['one@example.com'],cc:mode === 'reply_all' ? ['copy@example.com'] : [],bcc:[],
    subject:'Re: approved',body:'Approved text\nSignature',
    reply:{message_id:'original@example.test',account_id:'local1',identity_id:'id1',mode}
  }};
  const original = {id:3,headerMessageId:'original@example.test',external:false,
    folder:{id:'local1://Inbox',accountId:'local1',path:'/Inbox'}};
  const full = {headers:{'message-id':['<original@example.test>'],references:['<ancestor@example.test>']},body:'Original text'};
  const calls = {new:0,reply:[],send:0,delivered:0,removed:0,saved:0,queries:0};
  const records = {}, guards = new Set(), removedListeners = new Set(), attached = [];
  let details;
  const api = {
    accounts:{list:async()=>[{id:'account1',type:'pop3',identities:[{id:'id1',email:'sender@example.com'}]},
                             {id:'local1',type:'none',identities:[]}]},
    messengerUtilities:{parseMailboxString:async value=>value.split(',').map(v=>({email:(v.match(/<([^>]+)>/)?.[1] || v.trim())}))},
    storage:{local:{get:async()=>structuredClone(records),set:async data=>Object.assign(records,structuredClone(data)),remove:async key=>delete records[key]}},
    messages:{
      query:async query=>{calls.queries++;assert.deepEqual(query,{headerMessageId:'original@example.test',accountId:'local1',online:false});return {messages:[structuredClone(original)],id:null};},
      get:async id=>id === 3 ? structuredClone(original) : ({id,headerMessageId:'out@example.test',folder:{accountId:'account1',path:'/Sent'}}),
      getFull:async()=>structuredClone(full)
    },
    compose:{
      beginNew:async()=>{calls.new++;throw Error('must never create new');},
      beginReply:async(...args)=>{calls.reply.push(args);details={identityId:'id1',type:'reply',relatedMessageId:3,
        from:'Sender <sender@example.com>',to:['One <one@example.com>'],cc:mode === 'reply_all' ? ['Copy <copy@example.com>'] : [],
        bcc:[],newsgroups:[],followupTo:[],subject:'Re: original',plainTextBody:'Automatic quote\nAutomatic signature',isPlainText:true};return {id:7};},
      getComposeDetails:async()=>structuredClone(details),
      setComposeDetails:async(_id,changes)=>Object.assign(details,structuredClone(changes)),
      listAttachments:async()=>attached.map((a,i)=>({id:i,name:a.name,size:a.size})),
      removeAttachment:async(_id,id)=>attached.splice(id,1),
      addAttachment:async(_id,{file})=>{attached.push(file);return {id:attached.length-1};},
      getAttachmentFile:async(_id,id)=>attached[id],
      onBeforeSend:{addListener:fn=>guards.add(fn),removeListener:fn=>guards.delete(fn)},
      saveMessage:async()=>{calls.saved++;throw Error('must never save');},
      sendMessage:async(tabId,options)=>{
        calls.send++;assert.deepEqual(options,{mode:'sendNow'});
        for (const guard of guards) {if ((await guard({id:tabId},structuredClone(details)))?.cancel) throw Error('cancelled');}
        calls.delivered++;return {mode:'sendNow',headerMessageId:'out@example.test',messages:[{id:42}]};
      }
    },tabs:{remove:async()=>calls.removed++,
      onRemoved:{addListener:fn=>removedListeners.add(fn),removeListener:fn=>removedListeners.delete(fn)}}
  };
  return {job,api,calls,original,full,records,guards,removedListeners,attached,details:()=>details};
}

for (const [mode,native] of [['reply_all','replyToAll'],['reply_sender','replyToSender']]) {
  test(`${mode} uses a real native reply, exact approved body, sendNow and FCC`,async()=>{
    const f=fixture(mode);
    const result=await core.send(f.job,f.api);
    assert.equal(result.status,'sent');assert.equal(result.copy_status,'verified');
    assert.deepEqual(f.calls.reply,[[3,native,{identityId:'id1',isPlainText:true}]]);
    assert.equal(f.details().plainTextBody,f.job.payload.body);
    assert.equal(f.calls.new,0);assert.equal(f.calls.saved,0);assert.equal(f.calls.delivered,1);
    assert.equal(f.guards.size,0);assert.ok(f.calls.queries >= 3);
  });
}

test('missing, duplicate (including later pages), wrong-account and external originals never compose or send',async()=>{
  for (const variant of ['missing','duplicate','paged','wrong-account','external','wrong-header']) {
    const f=fixture();
    if (variant === 'missing') f.api.messages.query=async()=>({messages:[]});
    if (variant === 'duplicate') f.api.messages.query=async()=>({messages:[f.original,{...f.original,id:4}]});
    if (variant === 'paged') {
      f.api.messages.query=async()=>({messages:[f.original],id:'next'});
      f.api.messages.continueList=async()=>({messages:[{...f.original,id:4}]});
    }
    if (variant === 'wrong-account') f.original.folder.accountId='other';
    if (variant === 'external') f.original.external=true;
    if (variant === 'wrong-header') f.full.headers['message-id']=['<other@example.test>'];
    assert.equal((await core.send(f.job,f.api)).status,'failed',variant);
    assert.equal(f.calls.reply.length,0,variant);assert.equal(f.calls.send,0,variant);assert.equal(f.calls.new,0,variant);
  }
});

test('native reply creation failure never falls back to beginNew',async()=>{
  const f=fixture();f.api.compose.beginReply=async()=>{throw Error('no native reply');};
  assert.equal((await core.send(f.job,f.api)).status,'failed');
  assert.equal(f.calls.new,0);assert.equal(f.calls.send,0);
});

test('send is blocked during native composer creation and preparation',async()=>{
  const f=fixture();
  const compose=f.api.compose;
  const begin=compose.beginReply,set=compose.setComposeDetails;
  const early = [];
  let blocked=0;
  f.api.compose.beginReply=async(...args)=>{
    for (const guard of f.guards) {
      // These promises must stay pending until beginReply independently returns
      // its precise ID; awaiting them inside beginReply would deadlock the mock.
      early.push(guard({id:7},{relatedMessageId:3}));
      early.push(guard({id:8},{relatedMessageId:3}));
    }
    return begin(...args);
  };
  f.api.compose.setComposeDetails=async(...args)=>{
    for (const guard of f.guards) {assert.deepEqual(await guard({id:7},f.details()),{cancel:true});blocked++;}
    await set(...args);
  };
  assert.equal((await core.send(f.job,f.api)).status,'sent');assert.equal(blocked,1);
  assert.deepEqual(await early[0],{cancel:true});
  assert.equal(await early[1],undefined,'a manual reply to the same original must not be cancelled');
});

test('native creation rejection releases pending manual events without guessing a window',async()=>{
  const f=fixture(),events=[];
  f.api.compose.beginReply=async()=>{
    for (const guard of f.guards) events.push(guard({id:8},{relatedMessageId:3}));
    throw Error('native creation rejected without a tab');
  };
  const result=await core.send(f.job,f.api);
  assert.equal(result.status,'failed');assert.match(result.error,/without a precise composer ID/);
  assert.equal(await events[0],undefined);assert.equal(f.calls.send,0);assert.equal(f.calls.removed,0);
  assert.equal(f.guards.size,0);assert.equal(f.details(),undefined);
});

test('preparation failure keeps the exact-tab guard active until closure is confirmed',async()=>{
  const f=fixture();f.job.payload.cc=[];
  let enteredClose,finishClose;
  const closing=new Promise(resolve=>{enteredClose=resolve;});
  const closed=new Promise(resolve=>{finishClose=resolve;});
  f.api.tabs.remove=async id=>{
    assert.equal(id,7);f.calls.removed++;enteredClose();
    for (const guard of f.guards) {
      assert.deepEqual(await guard({id:7},f.details()),{cancel:true});
      assert.equal(await guard({id:8},f.details()),undefined);
    }
    await closed;
  };
  const sending=core.send(f.job,f.api);
  await closing;
  assert.equal(f.guards.size,1);assert.equal(f.calls.send,0);
  finishClose();
  assert.equal((await sending).status,'failed');assert.equal(f.guards.size,0);
  assert.equal(f.removedListeners.size,0);
});

test('failed close retains a blocking guard until the exact target is removed',async()=>{
  const f=fixture();f.job.payload.cc=[];
  f.api.tabs.remove=async()=>{f.calls.removed++;throw Error('close denied');};
  assert.equal((await core.send(f.job,f.api)).status,'failed');
  assert.equal(f.guards.size,1);assert.equal(f.removedListeners.size,1);
  for (const guard of f.guards) {
    assert.deepEqual(await guard({id:7},f.details()),{cancel:true});
    assert.equal(await guard({id:8},f.details()),undefined);
  }
  for (const listener of f.removedListeners) listener(8);
  assert.equal(f.guards.size,1,'removing another window cannot release target guard');
  for (const listener of f.removedListeners) listener(7);
  assert.equal(f.guards.size,0);assert.equal(f.removedListeners.size,0);
  assert.equal(f.calls.send,0);
});

test('cancelled and unknown sends revoke permits before close and retain guards on close failure',async()=>{
  for (const variant of ['cancelled','rejected','unconfirmed','confirmed']) {
    const f=fixture(),send=f.api.compose.sendMessage;
    if (variant === 'cancelled') f.api.compose.sendMessage=async(...args)=>{f.details().bcc=['hidden@example.com'];return send(...args);};
    if (variant === 'rejected') f.api.compose.sendMessage=async()=>{f.calls.send++;throw Error('native response lost');};
    if (variant === 'unconfirmed') f.api.compose.sendMessage=async()=>{f.calls.send++;return {mode:'sendLater',messages:[]};};
    let guardedDuringClose=false;
    f.api.tabs.remove=async()=>{
      for (const guard of f.guards) {
        assert.deepEqual(await guard({id:7},f.details()),{cancel:true},variant);
        assert.equal(await guard({id:8},f.details()),undefined,variant);
        guardedDuringClose=true;
      }
      throw Error('close denied');
    };
    const result=await core.send(f.job,f.api);
    assert.equal(result.status,variant === 'cancelled' ? 'failed' : variant === 'confirmed' ? 'sent' : 'unknown',variant);
    assert.equal(guardedDuringClose,true,variant);assert.equal(f.guards.size,1,variant);
    for (const guard of f.guards) assert.deepEqual(await guard({id:7},f.details()),{cancel:true},variant);
    assert.equal(f.calls.delivered,variant === 'confirmed' ? 1 : 0,variant);
  }
});

test('the authorized send permit cannot allow two concurrent target-window events',async()=>{
  const f=fixture();
  f.api.compose.sendMessage=async()=>{
    f.calls.send++;
    for (const guard of f.guards) {
      const first=guard({id:7},f.details());
      const second=guard({id:7},f.details());
      assert.equal(await first,undefined);
      assert.deepEqual(await second,{cancel:true});
    }
    f.calls.delivered++;
    return {mode:'sendNow',headerMessageId:'out@example.test',messages:[]};
  };
  assert.equal((await core.send(f.job,f.api)).status,'sent');assert.equal(f.calls.delivered,1);
});

test('native recipient scope must exactly match authorized To, Cc and Bcc before changes',async()=>{
  for (const field of ['to','cc','bcc']) {
    const f=fixture();f.job.payload[field]=['other@example.com'];
    assert.equal((await core.send(f.job,f.api)).status,'failed',field);
    assert.equal(f.calls.send,0);assert.equal(f.calls.removed,1);
  }
});

test('changed source/identity, wrong reply context, unexpected sender/body/recipients fail before send',async()=>{
  const variants = ['source','identity','account','related','type','from','body','to','cc','bcc','subject','vcard','pgp'];
  for (const variant of variants) {
    const f=fixture();const set=f.api.compose.setComposeDetails;
    f.api.compose.setComposeDetails=async(...args)=>{
      await set(...args);
      if (variant === 'source') f.full.body='Changed original';
      else if (variant === 'identity') f.api.accounts.list=async()=>[{id:'account1',identities:[{id:'id1',email:'other@example.com'}]}];
      else if (variant === 'account') f.original.folder.path='/Moved';
      else Object.assign(f.details(),{
        related:{relatedMessageId:9},type:{type:'new'},from:{from:'other@example.com'},body:{plainTextBody:'Extra signature'},
        to:{to:['other@example.com']},cc:{cc:[]},bcc:{bcc:['hidden@example.com']},subject:{subject:'Changed'},
        vcard:{attachVCard:true},pgp:{attachPublicPGPKey:true}
      }[variant]);
    };
    assert.equal((await core.send(f.job,f.api)).status,'failed',variant);
    assert.equal(f.calls.send,0,variant);assert.equal(f.calls.removed,1,variant);
  }
});

test('identity moved to another account fails even when its id and address match',async()=>{
  const f=fixture();f.job.payload.identity_account_id='different';
  assert.equal((await core.send(f.job,f.api)).status,'failed');assert.equal(f.calls.reply.length,0);
});

test('send-event guard cancels last-moment recipient or original changes',async()=>{
  for (const changed of ['recipient','original']) {
    const f=fixture();const send=f.api.compose.sendMessage;
    f.api.compose.sendMessage=async(...args)=>{
      if (changed === 'recipient') f.details().bcc=['hidden@example.com'];
      else f.full.body='Changed after preparation';
      return send(...args);
    };
    assert.equal((await core.send(f.job,f.api)).status,'failed',changed);
    assert.equal(f.calls.delivered,0);assert.equal(f.guards.size,0);
  }
});

test('reply attachments are explicit bytes; inherited ones are removed and final bytes checked',async()=>{
  const f=fixture(), bytes=Buffer.from('approved attachment');
  f.attached.push(new File(['inherited'],'old.txt'));
  f.job.payload.attachments=[{index:0,name:'approved.txt',size:bytes.length,type:'text/plain',sha256:createHash('sha256').update(bytes).digest('hex')}];
  assert.equal((await core.send(f.job,f.api,async()=>({data_base64:bytes.toString('base64'),next_offset:null}))).status,'sent');
  assert.equal(f.attached.length,1);assert.equal(f.attached[0].name,'approved.txt');
  assert.deepEqual(Buffer.from(await f.attached[0].arrayBuffer()),bytes);
});

test('replaced attachment with the same name and size is refused',async()=>{
  const f=fixture(),bytes=Buffer.from('approved');
  f.job.payload.attachments=[{index:0,name:'approved.txt',size:bytes.length,type:'text/plain',sha256:createHash('sha256').update(bytes).digest('hex')}];
  f.api.compose.getAttachmentFile=async()=>new File(['tampered'],'approved.txt');
  assert.equal((await core.send(f.job,f.api,async()=>({data_base64:bytes.toString('base64'),next_offset:null}))).status,'failed');
  assert.equal(f.calls.send,0);
});

test('reply recovery reports persisted unknown or unfinished work without new send',async()=>{
  const f=fixture();f.api.compose.sendMessage=async()=>{f.calls.send++;throw Error('lost acknowledgement');};
  await assert.rejects(core.execute(f.job,f.api,async()=>{throw Error('native host unavailable');}));
  const reports=[];await core.recover(f.api,async(...args)=>reports.push(args));
  assert.equal(reports[0][2].status,'unknown');assert.equal(f.calls.send,1);assert.equal(f.calls.new,0);
  f.records['pending:interrupted']={request_id:'interrupted',claim_token:'token'};
  await core.recover(f.api,async(...args)=>reports.push(args));
  assert.equal(reports[1][2].status,'unknown');assert.equal(f.calls.send,1);
});

test('HTML reply uses explicit HTML and browser canonicalization boundary; mutation fails',async()=>{
  const previous = globalThis.DOMParser;
  // Thunderbird supplies the real DOMParser. This stub tests routing/guard logic,
  // not HTML parsing or native editor rendering.
  globalThis.DOMParser = class {parseFromString(value){return {body:{innerHTML:value}};}};
  try {
    for (const mutated of [false,true]) {
      const f=fixture();f.job.payload.body_format='html';f.job.payload.body='<p>Approved signature</p>';
      const set=f.api.compose.setComposeDetails;
      if (mutated) f.api.compose.setComposeDetails=async(...args)=>{await set(...args);f.details().body+='<p>Unexpected signature</p>';};
      const result=await core.send(f.job,f.api);
      assert.equal(result.status,mutated ? 'failed' : 'sent');
      assert.equal(f.calls.delivered,mutated ? 0 : 1);
      assert.equal(f.details().deliveryFormat,'both');
    }
  } finally {
    if (previous === undefined) delete globalThis.DOMParser;
    else globalThis.DOMParser=previous;
  }
});
