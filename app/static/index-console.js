const consoleState={paused:false};const issue=document.querySelector('#run-error');const tail=document.querySelector('#log-tail');
function appendLog(text){if(!tail)return;const line=document.createElement('div');line.className='log-line';line.textContent=new Date().toISOString().slice(11,19)+' INFO '+text;tail.append(line);if(!consoleState.paused)tail.scrollTop=tail.scrollHeight;}
async function runAction(url,payload,upload=false){issue.textContent='回放中…';appendLog('REQUEST');try{const options={method:'POST',body:upload?payload:JSON.stringify(payload)};if(!upload)options.headers={'Content-Type':'application/json'};const response=await fetch(url,options);const result=await response.json();if(!response.ok)throw Error(result.message);appendLog('COMPLETE '+result.run_id);location.reload();}catch(error){issue.textContent=error.message;appendLog('FAIL '+error.message);}}
async function signAction(url,payload,label){
  const actorInput=document.querySelector('#actor-name');const actor=(actorInput?.value||'').trim();
  if(!actor){issue.textContent='请填写操作人工号/姓名，签署必须可追回。';return;}
  issue.textContent=label+'中…';appendLog(label+' REQUEST v'+payload.version);
  try{
    const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,actor})});
    const result=await response.json();
    if(!response.ok)throw Error(result.message);
    const sig=result.signoff;
    appendLog(label+' OK '+result.decision+' '+(sig?sig.credential_id:''));
    location.reload();
  }catch(error){issue.textContent=error.message;appendLog(label+' FAIL '+error.message);}
}
document.querySelector('#pause-log')?.addEventListener('click',event=>{consoleState.paused=!consoleState.paused;event.currentTarget.textContent=consoleState.paused?'继续':'暂停';});
document.querySelector('#replay').addEventListener('click',()=>runAction('/api/runs',{sample:document.querySelector('#stream-preset').value}));
document.querySelector('#signoff').addEventListener('click',()=>{
  const role=document.querySelector('#actor-role').value;
  if(role!=='复核人'){issue.textContent='角色权限不可混用：复核签发仅复核人可执行。';return;}
  signAction('/api/runs/'+window.indexBatch.id+'/review',{version:window.indexBatch.version,decision:'已签发'},'复核签发');
});
document.querySelector('#exception-release').addEventListener('click',()=>{
  const role=document.querySelector('#actor-role').value;
  if(role!=='提交人'){issue.textContent='例外放行仅提交人可发起，不得借用复核身份。';return;}
  const reason=window.prompt('例外放行须留痕：请填写紧急情形与业务理由（事后由复核人补复核）');
  if(reason===null)return;
  if(!reason.trim()){issue.textContent='例外放行必须填写理由。';return;}
  signAction('/api/runs/'+window.indexBatch.id+'/exception-release',{version:window.indexBatch.version,reason:reason.trim()},'例外放行');
});
document.querySelector('#load-stream').addEventListener('click',()=>{const file=document.querySelector('#event-file').files[0];if(!file){issue.textContent='请选择双写事件文件。';return;}const form=new FormData();form.append('file',file);runAction('/api/upload',form,true);});
document.querySelector('#doc-filter')?.addEventListener('input',event=>{for(const row of document.querySelectorAll('#doc-rows tr'))row.hidden=!row.textContent.includes(event.target.value);});
