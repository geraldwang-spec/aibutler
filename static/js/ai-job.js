(function(){
  const panel=document.getElementById('ai-job'); if(!panel)return;
  async function poll(){
    try{
      const response=await fetch(panel.dataset.statusUrl,{credentials:'same-origin'}); if(!response.ok)return;
      const job=await response.json();
      document.getElementById('job-status').textContent=job.status;
      document.getElementById('job-usage').textContent=`請求 ${job.calls} 次 · 輸入 ${job.input_tokens} / 輸出 ${job.output_tokens} tokens`;
      document.getElementById('job-error').textContent=job.error||'';
      if(job.result){const link=document.getElementById('job-result');link.href=job.result.url;link.hidden=false;link.textContent=job.result.message+' →';}
      if(['queued','running'].includes(job.status))setTimeout(poll,2500);
    }catch(error){document.getElementById('job-error').textContent='暫時無法取得進度。請重新整理；不會重新提交工作。';}
  }
  poll();
})();
