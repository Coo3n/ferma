"""Behavioral Node regressions for stale launch readiness and deleted details."""
import subprocess
from pathlib import Path

from _node import require_node

JS = Path(__file__).resolve().parents[2] / "frontend/js"


def test_run_dialog_invalidates_old_preflight_and_ignores_late_errors():
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={rdGo:{disabled:false},rdCheck:{},rdScen:{value:'one'},
 modal:{classList:{contains:()=>true}},rdTrialRow:{hidden:true},rdTrial:{checked:false},rdRepeat:{value:'1'}};
const requests=[],runs=[],runResponses=[];
const ctx={window:{},S:{scenarios:[{key:'one',params:{}},{key:'two',params:{}}],
 devices:[{serial:'a',online:true},{serial:'b',online:true}],hidden:new Set()},
 $:id=>nodes[id],setTimeout,clearTimeout,t:k=>k,esc:String,
 setHTML:(el,s)=>el.innerHTML=s,disableWithReason:(el,off)=>el.disabled=off,
 paramsRead:()=>({}),closeModal(){},toast(){},showRuns(){},
 post:async(url,payload)=>{if(url==='/api/run'){runs.push(payload);return new Promise(resolve=>runResponses.push(resolve));}
 return new Promise((resolve,reject)=>requests.push({resolve,reject,payload}));}};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
vm.runInContext('rdRenderTrial=()=>{}',ctx);
(async()=>{
 vm.runInContext("RD.picked=new Set(['a'])",ctx);
 const first=ctx.rdPreflight();requests[0].resolve({counts:{ready:1},devices:{a:{status:'ready'}}});await first;
 assert.equal(nodes.rdGo.disabled,false);
 vm.runInContext("RD.picked=new Set(['b']);rdRefresh();clearTimeout(RD.timer)",ctx);
 assert.equal(nodes.rdGo.disabled,true,'choice change must disable launch immediately');
 assert.equal(ctx.rdRunnable().length,0,'old phones must no longer be runnable');
 await ctx.rdGo();assert.equal(runs.length,0);
 const second=ctx.rdPreflight();requests[1].resolve({counts:{ready:1},devices:{b:{status:'ready'}}});await second;
 assert.deepEqual(Array.from(ctx.rdRunnable()),['b']);
 // Old failure must not erase readiness of a newer request.
 const old=ctx.rdPreflight(),current=ctx.rdPreflight();
 requests[3].resolve({counts:{ready:1},devices:{b:{status:'ready'}}});await current;
 requests[2].reject(new Error('old failure'));await old;
 assert.equal(nodes.rdGo.disabled,false);assert.deepEqual(Array.from(ctx.rdRunnable()),['b']);
 // Old success must not apply during the debounce before the new request starts.
 const late=ctx.rdPreflight();
 vm.runInContext("RD.picked=new Set(['a']);rdRefresh();clearTimeout(RD.timer)",ctx);
 requests[4].resolve({counts:{ready:1},devices:{b:{status:'ready'}}});await late;
 assert.equal(nodes.rdGo.disabled,true);assert.equal(ctx.rdRunnable().length,0);
 // The same readiness must not apply to another scenario, even without onchange.
 const fresh=ctx.rdPreflight();requests[5].resolve({counts:{ready:1},devices:{a:{status:'ready'}}});await fresh;
 nodes.rdScen.value='two';assert.equal(ctx.rdRunnable().length,0);
 // Re-rendering readiness while the first POST is pending must not allow a duplicate.
 nodes.rdScen.value='one';const launch=ctx.rdGo();ctx.rdRenderCheck();
 assert.equal(nodes.rdGo.disabled,true);await ctx.rdGo();assert.equal(runs.length,1);
 runResponses[0]({batch:'batch'});await launch;
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run([require_node(), "-e", script, str(JS / "rundialog.js")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_stale_popup_responses_do_not_restore_or_hide_other_scenario():
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={scSteps:{hidden:false},scPopups:{hidden:false,innerHTML:''}};
const requests=[];
const ctx={window:{},$:id=>nodes[id],esc:String,t:k=>k,setHTML:(el,s)=>el.innerHTML=s,
 api:url=>new Promise((resolve,reject)=>requests.push({resolve,reject,url}))};
vm.createContext(ctx);
for(const path of process.argv.slice(1))vm.runInContext(fs.readFileSync(path,'utf8'),ctx);
(async()=>{
 const old=ctx.popScenarioLoad('old');
 await ctx.renderScenarioSteps({key:'code',editable:false});
 requests[0].resolve({rules:[],packages:[],off:false});await old;
 assert.equal(nodes.scPopups.hidden,true,'late success must not reopen hidden old rules');
 const failed=ctx.popScenarioLoad('old'),current=ctx.popScenarioLoad('current');
 requests[2].resolve({rules:[],packages:[],off:false});await current;
 assert.equal(nodes.scPopups.hidden,false);
 requests[1].reject(new Error('old failure'));await failed;
 assert.equal(nodes.scPopups.hidden,false,'late failure must not hide current rules');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
    result = subprocess.run([require_node(), "-e", script, str(JS / "scenarios.js"), str(JS / "popups.js")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_missing_scenario_clears_step_and_popup_details():
    script = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={scParams:{innerHTML:'old'},scSteps:{innerHTML:'old steps',hidden:false},
 scPopups:{innerHTML:'old rules',hidden:false}};
const ctx={window:{},S:{scenario:null,scenarios:[]},POP:{scenKey:'deleted'},$:id=>nodes[id]};
vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ctx);
ctx.renderParams();
assert.equal(nodes.scParams.innerHTML,'');
assert.equal(nodes.scSteps.hidden,true);assert.equal(nodes.scSteps.innerHTML,'');
assert.equal(nodes.scPopups.hidden,true);assert.equal(nodes.scPopups.innerHTML,'');
assert.equal(ctx.POP.scenKey,null);
"""
    result = subprocess.run([require_node(), "-e", script, str(JS / "scenarios.js")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
