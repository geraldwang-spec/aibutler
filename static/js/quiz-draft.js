(function(){
 const form=document.getElementById('quiz-form');if(!form)return;
 const key='quiz-draft:'+form.dataset.quizId;
 try{
  if(form.dataset.finished==='1'){sessionStorage.removeItem(key);return;}
  const saved=JSON.parse(sessionStorage.getItem(key)||'{}');
  for(const input of form.elements){if(!input.name.startsWith('answer_'))continue;const values=saved[input.name]||[];if(['radio','checkbox'].includes(input.type))input.checked=values.includes(input.value);else input.value=values[0]||'';}
  form.addEventListener('change',save);form.addEventListener('input',save);
  function save(){const data={};for(const [name,value] of new FormData(form)){if(name.startsWith('answer_'))(data[name]??=[]).push(value);}sessionStorage.setItem(key,JSON.stringify(data));}
 }catch(error){/* Private mode or full storage: normal exam submission still works. */}
})();
