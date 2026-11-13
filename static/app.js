const csrf = document.querySelector('meta[name="csrf"]').content;
const messages = document.getElementById('messages');
const statusBox = document.getElementById('status');
const form = document.getElementById('ask');
const question = document.getElementById('question');
const send = document.getElementById('send');
let conversationId = null;
function addMessage(role, content, sources=[]) {
  const box = document.createElement('div'); box.className = 'bubble ' + role;
  const text = document.createElement('div'); text.textContent = content; box.appendChild(text);
  if (sources.length) {
    const detail = document.createElement('details');
    const summary = document.createElement('summary'); summary.textContent = '참고한 문서 ' + sources.length + '건'; detail.appendChild(summary);
    for (const s of sources) {
      const p = document.createElement('p');
      p.textContent = `${s.filename} · 구간 ${s.part} · 유사도 ${s.score}\n${s.text.slice(0,350)}`;
      detail.appendChild(p);
    }
    box.appendChild(detail);
  }
  messages.appendChild(box); messages.scrollTop = messages.scrollHeight;
}
form.addEventListener('submit', async e => {
  e.preventDefault(); const q=question.value.trim(); if(q.length<2) return;
  send.disabled=true; statusBox.textContent='매뉴얼 검색 및 답변 생성 중...'; addMessage('user',q); question.value='';
  try {
    const response = await fetch('/api/chat', {method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({question:q,conversation_id:conversationId,csrf})});
    const data = await response.json();
    if(!response.ok) throw new Error(data.detail || '요청에 실패했습니다.');
    addMessage('assistant',data.answer,data.sources); const isNew=conversationId===null;
    conversationId=data.conversation_id;
    if(isNew) {
      const b=document.createElement('button'); b.className='history-item'; b.dataset.id=conversationId;
      b.textContent=q.slice(0,70); document.getElementById('history').prepend(b);
    }
  } catch(err) { addMessage('assistant','오류: '+err.message); }
  finally { send.disabled=false; statusBox.textContent=''; question.focus(); }
});
document.getElementById('newChat').addEventListener('click',()=>{conversationId=null;messages.replaceChildren();addMessage('assistant','새 대화를 시작합니다.');});
document.getElementById('history').addEventListener('click',async e=>{
 const b=e.target.closest('[data-id]'); if(!b)return;
 try {
  const r=await fetch(`/api/conversations/${encodeURIComponent(b.dataset.id)}`);
  const data=await r.json(); if(!r.ok)throw new Error(data.detail||'불러오기 실패');
  conversationId=data.id; messages.replaceChildren();
  data.messages.forEach(m=>addMessage(m.role,m.content,m.sources));
 }catch(err){statusBox.textContent=err.message;}
});
