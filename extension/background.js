'use strict';
const HOST = 'com.thunderbird_mail_mcp.native_send';
let port = null;
let sequence = 0;
let busy = false;
let polling = false;
let recovered = false;
const pending = new Map();

function connect() {
  const current = browser.runtime.connectNative(HOST);
  port = current;
  current.onMessage.addListener(message => {
    const waiting = pending.get(message.id);
    if (!waiting) return;
    pending.delete(message.id);
    clearTimeout(waiting.timer);
    if (message.ok) waiting.resolve(message.result);
    else waiting.reject(new Error(message.error || 'Native host rejected request'));
  });
  current.onDisconnect.addListener(() => {
    // Read lastError, but don't log request contents or authentication data.
    void browser.runtime.lastError;
    if (port === current) port = null;
    recovered = false;
    for (const waiting of pending.values()) {
      clearTimeout(waiting.timer);
      waiting.reject(new Error('Native host disconnected'));
    }
    pending.clear();
  });
}

function request(message) {
  if (!port) connect();
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error('Native response timeout'));
    }, 10000);
    pending.set(id, {resolve, reject, timer});
    try { port.postMessage({...message, id}); }
    catch (error) {clearTimeout(timer); pending.delete(id); reject(error);}
  });
}

const report = (request_id, claim_token, result) => request({op:'complete',request_id,claim_token,result});
const fetchAttachment = (job,index,offset) => request({op:'attachment',request_id:job.request_id,claim_token:job.claim_token,index,offset});

async function poll() {
  if (polling) return;
  polling = true;
  try {
    if (!busy && !recovered) {
      await NativeSendCore.recover(browser, report);
      recovered = true;
    }
    const identities = (await browser.accounts.list(false)).flatMap(a => a.identities || [])
      .map(({id,email}) => ({id,email}));
    const job = await request({op:'poll', identities, features:['attachments_v1','draft_v1','html_v1'], accept:!busy && recovered});
    if (job) {
      busy = true;
      NativeSendCore.execute(job, browser, report, fetchAttachment).catch(() => {recovered = false;})
        .finally(() => {busy = false;});
    }
  } catch (_) { /* Keep bridge offline until the next successful native heartbeat. */ }
  finally {polling = false;}
}
setInterval(poll, 2000);
poll();
