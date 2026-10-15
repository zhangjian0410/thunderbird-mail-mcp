const {test} = require('node:test');
const assert = require('node:assert/strict');
const core = require('../extension/sender.js');

const job = {request_id: 'req-1', claim_token: 'token', payload: {
  identity_id: 'id1', from_email: 'sender@example.com', to: ['one@example.com'], cc: [], bcc: [],
  subject: '中文主题', body: '正文\n第二行'
}};
function fixture(outcome = {mode:'sendNow', headerMessageId:'abc@example.com', messages:[{id:42}]}) {
  const records = {};
  const calls = [];
  const api = {
    accounts: {list: async () => [{id:'account1',identities:[{id:'id1',email:'sender@example.com'}]}]},
    storage: {local: {
      get: async key => key === null ? {...records} : {[key]:records[key]},
      set: async data => Object.assign(records,structuredClone(data)),
      remove: async key => {delete records[key];}
    }},
    compose: {
      beginNew: async details => {calls.push([details]); return {id:7};},
      sendMessage: async (...args) => {calls.push(args); if (outcome instanceof Error) throw outcome; return outcome;}
    },
    messages: {
      get: async () => ({id:42,headerMessageId:'abc@example.com',folder:{id:'account1://Sent',accountId:'account1',path:'/Sent',name:'Sent'}})
    }
  };
  return {api,records,calls};
}
test('HTML uses actual HTML body and multipart alternative; draft never sends', async () => {
  for (const action of ['send','draft']) {
    const {api,calls} = fixture();
    api.compose.saveMessage = async () => ({mode:'draft',messages:[{id:9}]});
    api.tabs = {remove:async()=>{}};
    const body = '<table><tr><td>预算</td><td>50,000</td></tr></table>';
    const result = await core.send({...job,payload:{...job.payload,body,body_format:'html',action}},api);
    assert.equal(calls[0][0].body,body);
    assert.equal(calls[0][0].isPlainText,false);
    assert.equal(calls[0][0].deliveryFormat,'both');
    assert.equal(calls[0][0].plainTextBody,undefined);
    assert.equal(calls.length,action === 'draft' ? 1 : 2);
    assert.equal(result.status,action === 'draft' ? 'drafted' : 'sent');
  }
});
test('unknown body format fails before compose or send', async () => {
  const {api,calls} = fixture();
  assert.equal((await core.send({...job,payload:{...job.payload,body_format:'markdown'}},api)).status,'failed');
  assert.equal(calls.length,0);
});
test('send exact plaintext with selected identity; inherit FCC; verify saved copy', async () => {
  const {api,calls} = fixture();
  const result = await core.send(job,api);
  assert.deepEqual(calls, [[{identityId:'id1',to:['one@example.com'],cc:[],bcc:[],subject:'中文主题',plainTextBody:'正文\n第二行',isPlainText:true,deliveryFormat:'plaintext'}], [7, {mode:'sendNow'}]]);
  assert.equal(result.status,'sent');
  assert.equal(result.copy_status,'verified');
  assert.equal(result.copies[0].folder.path,'/Sent');
});
test('missing or unreadable copy does not turn a successful send into another send', async () => {
  const {api,calls} = fixture();
  api.messages.get = async () => {throw new Error('copy unavailable');};
  const result = await core.send(job,api);
  assert.equal(result.status,'sent');
  assert.equal(result.copy_status,'not_verified');
  assert.equal(calls.length,2);
});
test('API error may happen after delivery and must be unknown without retry', async () => {
  const {api,calls} = fixture(new Error('FCC failed after SMTP'));
  const result = await core.send(job,api);
  assert.equal(result.status,'unknown');
  assert.equal(calls.length,2);
});
test('queued mail or missing Message-ID is not reported as sent', async () => {
  for (const outcome of [{mode:'sendLater',messages:[]},{mode:'sendNow',messages:[]}]) {
    const {api} = fixture(outcome);
    assert.equal((await core.send(job,api)).status,'unknown');
  }
});
test('changed identity fails before any mail is sent', async () => {
  const {api,calls} = fixture();
  api.accounts.list = async () => [{identities:[{id:'id1',email:'other@example.com'}]}];
  assert.equal((await core.send(job,api)).status,'failed');
  assert.equal(calls.length,0);
});
test('failed acknowledgement persists result and recovery reports without resending', async () => {
  const {api,calls,records} = fixture();
  await assert.rejects(core.execute(job,api,async()=>{throw new Error('lost ack');}));
  assert.equal(Object.values(records)[0].result.status,'sent');
  const reports = [];
  await core.recover(api,async(...args)=>reports.push(args));
  assert.equal(calls.length,2);
  assert.equal(reports[0][2].status,'sent');
  assert.deepEqual(records,{});
});
test('crash during send is recovered as unknown; never send it again', async () => {
  const {api,calls,records} = fixture();
  records['pending:req-1'] = {request_id:'req-1',claim_token:'token'};
  let status;
  await core.recover(api,async(_id,_token,result)=>{status=result.status;});
  assert.equal(status,'unknown');
  assert.equal(calls.length,0);
});
