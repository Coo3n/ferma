"""Drafts and PATCH payloads: editing one account must not affect another."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend/js/accounts.js"


def test_account_editor_drafts_and_failed_save():
    script = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const nodes = new Proxy({}, {get: (o, k) => o[k] ||= {
  textContent: '', dataset: {}, hidden: false, disabled: false, setAttribute() {}, focus() {},
  removeAttribute() {}, querySelector() {return null;}
}});
const ctx = {t:k=>k, esc:s=>String(s??''), PLATFORM_NAMES:{vk:'VK'}, S:{devices:[], view:''},
 window:{addEventListener(){}}, document:{addEventListener(){},querySelectorAll(){return [];}}, setInterval(){},
 $:id=>nodes[id], toast(){}, setText:(el,s)=>el.textContent=s};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + `
 this.renderDetail=renderAccDetail;
 renderAccounts = () => {};
 renderAccDetail = () => {};
 this.A=ACC; this.edit=accDraftSet; this.save=accSaveDetail;
`, ctx);
(async () => {
 ctx.A.items=[{id:'a',login:'alice',platform:'vk',status:'active',note:''},
              {id:'b',login:'bob',platform:'vk',status:'new',note:''}];
 ctx.A.active='a';
 ctx.renderDetail();
 assert.ok(nodes.accDetail.innerHTML.includes('alice'),'first account renders without existing editor focus');
 ctx.edit('note','draft A');
 ctx.A.active='b'; ctx.edit('login','new bob');
 assert.equal(ctx.A.drafts.get('a').note,'draft A');
 assert.equal(ctx.A.items[1].login,'bob');
 let payload;
 ctx.api=async (url, opts)=>{payload=JSON.parse(opts.body); throw Error('offline');};
 await ctx.save();
 assert.equal(ctx.A.drafts.get('b').login,'new bob');
 assert.equal(ctx.A.errors.get('b'),'offline');
 assert.ok(!('password' in payload));
 ctx.api=async (url,opts)=>({...ctx.A.items[1],...JSON.parse(opts.body)});
 await ctx.save();
 assert.equal(ctx.A.items[1].login,'new bob');
 assert.ok(!ctx.A.drafts.has('b'));
 assert.equal(ctx.A.drafts.get('a').note,'draft A');
 ctx.A.active='a'; ctx.edit('note','');
 assert.ok(!ctx.A.drafts.has('a'), 'reverting a field clears dirty state');
 ctx.edit('login','   '); let calls=0;
 ctx.api=async()=>{calls++;}; await ctx.save();
 assert.equal(calls,0,'blank login never submitted');
 ctx.edit('login','alice'); ctx.edit('password','new-secret');
 ctx.api=async (url,opts)=>{payload=JSON.parse(opts.body); return ctx.A.items[0];};
 await ctx.save(); assert.equal(payload.password,'new-secret');
 // A list reload can replace objects while PATCH is in flight.
 ctx.edit('note','latest'); let release;
 ctx.api=()=>new Promise(resolve=>{release=resolve;});
 const saving=ctx.save();
 ctx.A.items=ctx.A.items.map(a=>({...a}));
 release({...ctx.A.items[0],note:'latest'}); await saving;
 assert.equal(ctx.A.items[0].note,'latest','save must update current collection, not a detached item');
 ctx.edit('password','typed'); ctx.edit('password','');
 assert.ok(!ctx.A.drafts.has('a'),'empty password preserves the existing password');
 // Responses from an older read cannot overwrite a newer mutation.
 let releaseLoad;
 ctx.api=path=>path==='/api/accounts' ? new Promise(resolve=>{releaseLoad=resolve;}) : Promise.resolve({counters:{}});
 const loading=ctx.loadAccounts(); ctx.A.revision++;
 releaseLoad([{...ctx.A.items[0],note:'stale read'}]); await loading;
 assert.equal(ctx.A.items[0].note,'latest','stale load overwrote the saved value');
 // The phone picker and editor serialize writes to the same account.
 let releaseBind, bindCalls=0;
 ctx.api=()=>{bindCalls++;return new Promise(resolve=>{releaseBind=resolve;});};
 const binding=ctx.accBind('a','phone-1');
 await ctx.accBind('a','phone-2');
 assert.equal(bindCalls,1,'duplicate bindings sent while pending');
 releaseBind({...ctx.A.items[0],serial:'phone-1'}); await binding;
 assert.equal(ctx.A.items[0].serial,'phone-1');
})().catch(e=>{console.error(e);process.exit(1)});
"""
    subprocess.run([require_node(), "-e", script, str(JS)], check=True,
                   capture_output=True, text=True)
