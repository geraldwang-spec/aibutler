// Isolated DOM harness: no browser/server, accounts or external API calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function node(value = '') {
  return {value, disabled: false, hidden: false, options: [], dataset: {}, events: {},
    addEventListener(type, callback) { this.events[type] = callback; },
    dispatchEvent(event) { this.events[event.type]?.(event); },
    setAttribute(key, value) { this[key] = value; },
    add(option) { this.options.push(option); }, focus() {}, scrollTop: 0};
}
async function run() {
  const ids = Object.fromEntries(['question-import-form','question-editor','editor-lines','editor-format',
    'import-subject','import-create-subject','import-new-subject','import-subject-status','import-manage-subject',
    'import-file-pane','import-text-pane','editor-count','editor-example','editor-clear'].map(id => [id,node()]));
  const form=ids['question-import-form'], file=node('selected.pdf'), csrf=node('test-csrf'), radio=node('text');
  const draft='尚未儲存的題目\n答案：A';
  ids['question-editor'].value=draft;
  ids['import-new-subject'].value='英文';
  ids['import-create-subject'].dataset.url='/imports/subjects';
  ids['import-manage-subject'].dataset.url='/records/subjects';
  form.querySelector = selector => selector.includes('csrf_token') ? csrf : selector.includes('source_mode') ? radio : file;
  form.querySelectorAll=()=>[radio];
  let finish, posted;
  const context={document:{getElementById:id=>ids[id]},
    window:{location:{origin:'http://localhost'},confirm:()=>true},URL,URLSearchParams,
    Event:class { constructor(type){this.type=type;} },
    Option:class { constructor(text,value){this.text=text;this.value=value;} },
    fetch:async (url,options)=>{ posted={url,options}; return new Promise(resolve=>{finish=resolve;}); }};
  vm.runInNewContext(fs.readFileSync('static/js/question-workspace.js','utf8'),context);
  const pending=ids['import-create-subject'].events.click();
  let prevented=false;
  form.events.submit({preventDefault(){prevented=true;}});
  assert.equal(prevented,true);
  assert.equal(posted.options.body.get('csrf_token'),'test-csrf');
  finish({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>({
    ok:true,subject:{id:7,subject_name:'英文'},message:'已新增'})});
  await pending;
  assert.equal(ids['import-subject'].value,'7');
  assert.equal(ids['import-subject'].options.length,1);
  assert.equal(ids['question-editor'].value,draft);
  assert.equal(file.value,'selected.pdf');
  assert.equal(ids['import-create-subject'].disabled,false);
  assert.equal(ids['import-manage-subject'].href,'/records/subjects?subject_id=7');
  // A network failure must also preserve the editor/file and restore controls.
  ids['import-new-subject'].value='歷史';
  const failed=ids['import-create-subject'].events.click();
  finish({ok:false,redirected:false,status:503,headers:{get:()=> 'text/html'}});
  await failed;
  assert.equal(ids['question-editor'].value,draft);
  assert.equal(file.value,'selected.pdf');
  assert.equal(ids['import-subject-status'].role,'alert');
  assert.equal(ids['import-create-subject'].disabled,false);
  console.log('Inline subject UI: success, pending submit and failure preservation passed.');
}
run().catch(error=>{console.error(error);process.exitCode=1;});
