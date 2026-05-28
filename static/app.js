/* app.js — Cô giáo Thắm UFM Chatbot Frontend (v3 — Onboarding + Enrollment) */
const state = {
  sessionId: '',
  isLoading: false,
  messages: [],
  hasWelcome: true,
  guestProfile: null,
  enrollmentId: null,
  coThamXung: null, // "cô" hoặc "em" — xác định từ vai vế user
  ttsAvailable: false, // TTS sidecar có sẵn không
  currentAudio: null, // Audio đang phát (nếu có)
};

const $ = (s) => document.querySelector(s);
const chatArea = () => $('#chat-area');
const inputEl = () => $('#msg-input');

// Tạo câu chờ động dựa vào vai vế xưng hô
// Nếu user xưng "em" → cô Thắm xưng "cô" → "Đợi cô Thắm xíu nha"
// Nếu user xưng "anh/chị/thầy/cô" → cô Thắm xưng "em" → "Đợi em Thắm xíu nha"
function getTypingMessage() {
  const xung = state.coThamXung || _guessInitialXung();
  const name = xung === 'cô' ? 'cô Thắm' : 'em Thắm';
  const messages = [
    `Đợi ${name} xíu nha, đang tìm thông tin trên website UFM...`,
    `Đợi ${name} xíu nha, đang kiểm tra dữ liệu từ trường...`,
    `Đợi ${name} xíu nha, đang tra cứu thông tin chính xác nhất...`,
    `Đợi ${name} xíu nha, một chút là có câu trả lời liền...`,
    `${xung === 'cô' ? 'Để cô' : 'Để em'} xem thông tin mới nhất cho ${xung === 'cô' ? 'em' : 'mình'} nhé...`,
  ];
  return messages[Math.floor(Math.random() * messages.length)];
}

// Đoán xưng hô ban đầu từ năm sinh (trước khi nhận metadata từ backend)
function _guessInitialXung() {
  if (!state.guestProfile) return 'cô'; // mặc định xưng cô
  const age = new Date().getFullYear() - state.guestProfile.birth_year;
  return age <= 26 ? 'cô' : 'em'; // trẻ → cô xưng "cô", lớn tuổi → cô xưng "em"
}

marked.setOptions({ breaks: true, gfm: true });
function renderMd(text) { return DOMPurify.sanitize(marked.parse(text), { ADD_ATTR: ['target'] }); }
function now() { return new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }); }
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function scrollBottom() { const a = chatArea(); requestAnimationFrame(() => { a.scrollTop = a.scrollHeight; }); }

// ══════════════════════════════════
// ONBOARDING GATE
// ══════════════════════════════════
function toggleStep1Next() {
  $('#step1-next').disabled = !$('#consent-check').checked;
}

function goToStep(n) {
  document.querySelectorAll('.onboard-step').forEach(el => el.style.display = 'none');
  $(`#ob-step-${n}`).style.display = 'block';
  document.querySelectorAll('.stepper .step').forEach(el => {
    const s = parseInt(el.dataset.step);
    el.classList.toggle('active', s <= n);
    el.classList.toggle('done', s < n);
  });
  if (n === 3) updateSummary();
}

function validateAndGoStep3() {
  let valid = true;
  const name = $('#ob-name').value.trim();
  const birth = parseInt($('#ob-birth').value);
  const edu = $('#ob-edu').value;

  $('#err-name').textContent = '';
  $('#err-birth').textContent = '';
  $('#err-edu').textContent = '';

  if (!name) { $('#err-name').textContent = 'Vui lòng nhập họ tên'; valid = false; }
  if (!birth || birth < 1950 || birth > 2010) { $('#err-birth').textContent = 'Năm sinh từ 1950 đến 2010'; valid = false; }
  if (!edu) { $('#err-edu').textContent = 'Vui lòng chọn trình độ'; valid = false; }
  if (valid) goToStep(3);
}

function updateSummary() {
  const eduLabels = { dai_hoc: 'Đại học', sau_dai_hoc: 'Thạc sĩ', cao_dang: 'Cao đẳng/Khác' };
  $('#sum-name').textContent = $('#ob-name').value.trim();
  $('#sum-birth').textContent = $('#ob-birth').value;
  $('#sum-edu').textContent = eduLabels[$('#ob-edu').value] || '-';
  $('#sum-contact').textContent = $('#ob-contact').value.trim() || '(chưa nhập)';
}

async function submitOnboarding() {
  const contact = $('#ob-contact').value.trim();
  if (!contact) { $('#err-contact').textContent = 'Vui lòng nhập email hoặc số điện thoại'; return; }
  $('#err-contact').textContent = '';
  $('#err-submit').textContent = '';
  $('#submit-ob').disabled = true;
  $('#submit-ob').textContent = 'Đang xử lý...';

  const body = {
    full_name: $('#ob-name').value.trim(),
    birth_year: parseInt($('#ob-birth').value),
    education_level: $('#ob-edu').value,
    education_detail: $('#ob-edu-detail').value.trim(),
    contact: contact,
    consent_given: true,
  };

  try {
    const resp = await fetch('/api/guest/register', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) { $('#err-submit').textContent = data.detail || 'Có lỗi xảy ra'; $('#submit-ob').disabled = false; $('#submit-ob').textContent = 'Bắt đầu chat với Cô Thắm 🎓'; return; }

    state.sessionId = data.session_id;
    state.guestProfile = body;
    sessionStorage.setItem('ufm_session', data.session_id);
    sessionStorage.setItem('ufm_profile', JSON.stringify(body));
    showChatScreen();
  } catch (e) {
    $('#err-submit').textContent = 'Lỗi kết nối, vui lòng thử lại';
    $('#submit-ob').disabled = false;
    $('#submit-ob').textContent = 'Bắt đầu chat với Cô Thắm 🎓';
  }
}

function showChatScreen() {
  $('#onboarding-screen').style.display = 'none';
  $('#chat-screen').style.display = 'block';
  const profile = state.guestProfile;
  if (profile) {
    const firstName = profile.full_name.split(' ').pop();
    const eduLabels = { dai_hoc: 'Đại học', sau_dai_hoc: 'Thạc sĩ', cao_dang: 'Cao đẳng' };
    const eduText = eduLabels[profile.education_level] || profile.education_level;
    const greeting = `Dạ chào ${profile.full_name}! Cô Thắm đây ạ 😊 Cô thấy ${firstName} đang có nền tảng ${eduText} rồi — cô sẵn sàng hỗ trợ ${firstName} tìm hiểu chương trình phù hợp nhất nhé. ${firstName} muốn hỏi về điều gì trước ạ?`;
    setTimeout(() => { addBotGreeting(greeting); }, 500);
  }
}

function addBotGreeting(text) {
  hideWelcome();
  const botEl = addBotBubble();
  botEl.querySelector('.bot-message-content').innerHTML = renderMd(text);
  renderSuggestions(['Trường có những ngành thạc sĩ nào?', 'Học phí chương trình thạc sĩ?', 'Điều kiện đầu vào thạc sĩ?']);
  scrollBottom();
}

// ══════════════════════════════════
// CHAT UI
// ══════════════════════════════════
function hideWelcome() { const w = $('.welcome'); if (w) { w.remove(); state.hasWelcome = false; } }

function addUserBubble(text) {
  hideWelcome();
  const html = `<div class="message user"><div class="msg-content"><div class="bubble user-bubble">${esc(text)}</div><div class="msg-time">${now()}</div></div></div>`;
  chatArea().insertAdjacentHTML('beforeend', html); scrollBottom();
}

function addBotBubble() {
  const id = 'bot-' + Date.now();
  const html = `<div class="message bot" id="${id}"><div class="msg-avatar">👩‍🏫</div><div class="msg-content"><div class="bubble bot-bubble"><div class="bot-message-content"></div></div><div class="msg-time">${now()}</div></div></div>`;
  chatArea().insertAdjacentHTML('beforeend', html); scrollBottom();
  return document.getElementById(id);
}

function showTyping() {
  hideTyping();
  const msg = getTypingMessage();
  const html = `<div class="typing" id="typing-indicator"><div class="msg-avatar">👩‍🏫</div><div class="typing-bubble"><span class="typing-text">${msg}</span><div class="dots"><span></span><span></span><span></span></div></div></div>`;
  chatArea().insertAdjacentHTML('beforeend', html); scrollBottom();
}
function hideTyping() { const t = $('#typing-indicator'); if (t) t.remove(); }

function renderSources(el, sources) {
  if (!sources || !sources.length) return;
  const chips = sources.slice(0, 3).map(source => {
    if (typeof source === 'object' && source.url) {
      const icon = source.type === 'pdf' ? '📄' : '🔗';
      const title = source.title || 'Xem nguồn';
      return `<a class="source-chip" href="${esc(source.url)}" target="_blank" rel="noopener noreferrer" title="${esc(source.url)}">${icon} ${esc(title)}</a>`;
    }
    const label = source.split('/').pop().substring(0, 30) || 'UFM';
    return `<a class="source-chip" href="${esc(source)}" target="_blank" title="${esc(source)}">🔗 ${esc(label)}</a>`;
  }).join('');
  const div = document.createElement('div'); div.className = 'sources-row';
  div.innerHTML = `<span class="sources-label">Nguồn tham khảo:</span>${chips}`;
  const bubble = el.querySelector('.bot-bubble');
  if (bubble) bubble.appendChild(div); else el.querySelector('.msg-content').appendChild(div);
}

function renderSuggestions(suggestions) {
  removeSuggestions();
  if (!suggestions || !suggestions.length) return;
  const chips = suggestions.map(s => `<button class="suggestion-chip" onclick="askQuestion('${esc(s)}')">${esc(s)}</button>`).join('');
  const div = document.createElement('div'); div.className = 'suggestions'; div.id = 'active-suggestions'; div.innerHTML = chips;
  chatArea().appendChild(div); scrollBottom();
}
function removeSuggestions() { const s = $('#active-suggestions'); if (s) s.remove(); }

// ══════════════════════════════════
// ENROLLMENT UI (simplified inline card)
// ══════════════════════════════════
function showEnrollmentCard() {
  const html = `<div class="enrollment-card" id="enrollment-panel">
    <div class="enroll-header"><h3>📋 Hồ sơ đăng ký nhập học UFM</h3><p>Điền thông tin và upload giấy tờ cần thiết</p></div>
    <div class="enroll-tabs">
      <button class="enroll-tab active" onclick="switchEnrollStep(1)">1. Cá nhân</button>
      <button class="enroll-tab" onclick="switchEnrollStep(2)">2. Học vấn</button>
      <button class="enroll-tab" onclick="switchEnrollStep(3)">3. Giấy tờ</button>
    </div>
    <div id="enroll-step-1" class="enroll-content">
      <input type="text" id="en-ho-ten" placeholder="Họ và tên đầy đủ *">
      <input type="text" id="en-ngay-sinh" placeholder="Ngày sinh (DD/MM/YYYY) *">
      <select id="en-gioi-tinh"><option value="">Giới tính *</option><option>Nam</option><option>Nữ</option><option>Khác</option></select>
      <input type="text" id="en-cmnd" placeholder="Số CMND/CCCD *">
      <input type="text" id="en-dia-chi" placeholder="Địa chỉ thường trú *">
      <input type="email" id="en-email" placeholder="Email *">
      <input type="tel" id="en-sdt" placeholder="Số điện thoại *">
      <button class="ob-btn primary" onclick="submitEnrollStep(1)">Lưu & Tiếp theo →</button>
    </div>
    <div id="enroll-step-2" class="enroll-content" style="display:none">
      <input type="text" id="en-truong" placeholder="Trường ĐH đã tốt nghiệp *">
      <input type="text" id="en-nganh" placeholder="Ngành học *">
      <input type="number" id="en-nam-tn" placeholder="Năm tốt nghiệp *">
      <select id="en-xep-loai"><option value="">Xếp loại *</option><option>Xuất sắc</option><option>Giỏi</option><option>Khá</option><option>Trung bình khá</option><option>Trung bình</option></select>
      <input type="text" id="en-nganh-dk" placeholder="Ngành ThS/TS muốn đăng ký *">
      <select id="en-bac"><option value="">Bậc học *</option><option>Thạc sĩ</option><option>Tiến sĩ</option></select>
      <button class="ob-btn primary" onclick="submitEnrollStep(2)">Lưu & Tiếp theo →</button>
    </div>
    <div id="enroll-step-3" class="enroll-content" style="display:none">
      <p class="enroll-note">Upload scan/ảnh chụp rõ nét (PDF, JPG, PNG — tối đa 10MB/file)</p>
      <div class="upload-zone" data-key="bang_tot_nghiep"><label>📜 Bằng tốt nghiệp ĐH <span class="required">*</span></label><input type="file" accept=".pdf,.jpg,.jpeg,.png" onchange="uploadDoc(this,'bang_tot_nghiep')"><div class="upload-status"></div></div>
      <div class="upload-zone" data-key="bang_diem"><label>📊 Bảng điểm toàn khóa <span class="required">*</span></label><input type="file" accept=".pdf,.jpg,.jpeg,.png" onchange="uploadDoc(this,'bang_diem')"><div class="upload-status"></div></div>
      <div class="upload-zone" data-key="cmnd_cccd_scan"><label>🪪 CMND/CCCD (2 mặt) <span class="required">*</span></label><input type="file" accept=".pdf,.jpg,.jpeg,.png" onchange="uploadDoc(this,'cmnd_cccd_scan')"><div class="upload-status"></div></div>
      <div class="upload-zone" data-key="anh_the"><label>📷 Ảnh thẻ 3x4/4x6 <span class="required">*</span></label><input type="file" accept=".jpg,.jpeg,.png" onchange="uploadDoc(this,'anh_the')"><div class="upload-status"></div></div>
      <div class="upload-zone" data-key="chung_chi_ngoai_ngu"><label>📝 Chứng chỉ ngoại ngữ <span class="optional">(không bắt buộc)</span></label><input type="file" accept=".pdf,.jpg,.jpeg,.png" onchange="uploadDoc(this,'chung_chi_ngoai_ngu')"><div class="upload-status"></div></div>
      <button class="ob-btn primary cta-btn" onclick="submitEnrollment()">📤 Nộp hồ sơ</button>
    </div>
    <div class="field-error center-error" id="enroll-error"></div>
  </div>`;
  chatArea().insertAdjacentHTML('beforeend', html); scrollBottom();
}

function switchEnrollStep(n) {
  document.querySelectorAll('.enroll-content').forEach(el => el.style.display = 'none');
  $(`#enroll-step-${n}`).style.display = 'block';
  document.querySelectorAll('.enroll-tab').forEach((el, i) => el.classList.toggle('active', i + 1 === n));
}

async function startEnrollment() {
  try {
    const resp = await fetch('/api/enrollment/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: state.sessionId }),
    });
    const data = await resp.json();
    if (data.success) { state.enrollmentId = data.enrollment_id; showEnrollmentCard(); }
  } catch (e) { console.error('Enrollment start error:', e); }
}

async function submitEnrollStep(step) {
  const data = {};
  if (step === 1) {
    data.ho_ten = $('#en-ho-ten').value.trim();
    data.ngay_sinh = $('#en-ngay-sinh').value.trim();
    data.gioi_tinh = $('#en-gioi-tinh').value;
    data.cmnd_cccd = $('#en-cmnd').value.trim();
    data.dia_chi = $('#en-dia-chi').value.trim();
    data.email = $('#en-email').value.trim();
    data.sdt = $('#en-sdt').value.trim();
  } else {
    data.truong_dai_hoc = $('#en-truong').value.trim();
    data.nganh_hoc = $('#en-nganh').value.trim();
    data.nam_tot_nghiep = $('#en-nam-tn').value.trim();
    data.xep_loai = $('#en-xep-loai').value;
    data.nganh_dang_ky = $('#en-nganh-dk').value.trim();
    data.bac_hoc = $('#en-bac').value;
  }
  const form = new FormData();
  form.append('enrollment_id', state.enrollmentId);
  form.append('step', step);
  form.append('data', JSON.stringify(data));
  try {
    const resp = await fetch('/api/enrollment/info', { method: 'POST', body: form });
    const result = await resp.json();
    if (resp.ok) { switchEnrollStep(step + 1); } else { $('#enroll-error').textContent = result.detail || 'Lỗi'; }
  } catch (e) { $('#enroll-error').textContent = 'Lỗi kết nối'; }
}

async function uploadDoc(input, docKey) {
  const file = input.files[0]; if (!file) return;
  const status = input.closest('.upload-zone').querySelector('.upload-status');
  if (file.size > 10 * 1024 * 1024) { status.textContent = '❌ File quá lớn (max 10MB)'; status.className = 'upload-status error'; return; }
  status.textContent = '⏳ Đang upload...'; status.className = 'upload-status';
  const form = new FormData();
  form.append('enrollment_id', state.enrollmentId);
  form.append('doc_key', docKey);
  form.append('file', file);
  try {
    const resp = await fetch('/api/enrollment/upload', { method: 'POST', body: form });
    const data = await resp.json();
    if (resp.ok) { status.textContent = `✅ ${file.name}`; status.className = 'upload-status success'; }
    else { status.textContent = `❌ ${data.detail}`; status.className = 'upload-status error'; }
  } catch (e) { status.textContent = '❌ Lỗi upload'; status.className = 'upload-status error'; }
}

async function submitEnrollment() {
  try {
    const resp = await fetch('/api/enrollment/submit', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enrollment_id: state.enrollmentId }),
    });
    const data = await resp.json();
    if (resp.ok) {
      const panel = $('#enrollment-panel'); if (panel) panel.remove();
      const name = state.guestProfile?.full_name?.split(' ').pop() || 'bạn';
      const contact = state.guestProfile?.contact || '';
      const botEl = addBotBubble();
      botEl.querySelector('.bot-message-content').innerHTML = renderMd(
        `Dạ cô đã nhận được đầy đủ hồ sơ của ${name} rồi ạ! 🎉 Bộ phận tuyển sinh UFM sẽ kiểm tra và liên hệ lại trong vòng 2-3 ngày làm việc qua ${contact}. ${name} có thể hỏi thêm cô bất cứ điều gì trong lúc chờ đợi nha!`
      );
    } else { $('#enroll-error').textContent = data.detail || 'Chưa đủ hồ sơ'; }
  } catch (e) { $('#enroll-error').textContent = 'Lỗi kết nối'; }
}

// ══════════════════════════════════
// HANDOFF
// ══════════════════════════════════
function showHandoffForm() {
  const html = `<div class="handoff-card" id="handoff-form"><h3>📞 Kết nối với tư vấn viên UFM</h3><p class="subtitle">Để lại thông tin, phòng Sau đại học sẽ liên hệ sớm nhất ạ</p><input type="text" id="hf-name" placeholder="Họ và tên *" required><input type="tel" id="hf-phone" placeholder="Số điện thoại *" required><input type="email" id="hf-email" placeholder="Email"><select id="hf-interest"><option value="">-- Ngành quan tâm --</option><option>Thạc sĩ Tài chính - Ngân hàng</option><option>Thạc sĩ Quản trị kinh doanh</option><option>Thạc sĩ Kế toán</option><option>Thạc sĩ Marketing</option><option>Tiến sĩ QTKD</option><option>Chưa rõ, cần tư vấn</option></select><button class="handoff-submit" onclick="submitHandoff()">Gửi thông tin</button></div>`;
  chatArea().insertAdjacentHTML('beforeend', html); scrollBottom();
}
async function submitHandoff() {
  const name = $('#hf-name').value.trim(); const phone = $('#hf-phone').value.trim();
  if (!name || !phone) { alert('Vui lòng nhập họ tên và SĐT'); return; }
  try {
    const resp = await fetch('/api/handoff', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, phone, email: $('#hf-email').value.trim(), interest: $('#hf-interest').value, session_id: state.sessionId })
    });
    const data = await resp.json();
    $('#handoff-form').innerHTML = `<div class="handoff-success">✅ ${data.message}</div>`;
  } catch(e) { alert('Có lỗi, vui lòng thử lại'); }
}

// ══════════════════════════════════
// SEND MESSAGE
// ══════════════════════════════════
async function sendMessage(text) {
  if (state.isLoading || !text.trim()) return;
  state.isLoading = true; removeSuggestions();
  addUserBubble(text.trim()); inputEl().value = ''; autoResize(); toggleSendBtn(); showTyping();

  try {
    const resp = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text.trim(), session_id: state.sessionId }) });
    if (!resp.ok) throw new Error('HTTP ' + resp.status);

    hideTyping();
    const botEl = addBotBubble();
    const contentEl = botEl.querySelector('.bot-message-content');
    const reader = resp.body.getReader(); const decoder = new TextDecoder();
    let fullText = '', metadata = null, buffer = '';

    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n'); buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data: ') || line === 'data: [DONE]') continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.done) metadata = data;
          else if (data.content) { fullText += data.content; contentEl.innerHTML = renderMd(fullText); scrollBottom(); }
        } catch(e) {}
      }
    }
    if (buffer.startsWith('data: ') && buffer !== 'data: [DONE]') {
      try { const data = JSON.parse(buffer.slice(6)); if (data.done) metadata = data; } catch(e) {}
    }

    if (metadata) {
      renderSources(botEl, metadata.sources);
      renderSuggestions(metadata.suggestions);
      if (metadata.requires_handoff) showHandoffForm();
      if (metadata.action === 'start_enrollment') startEnrollment();
      // Lưu ngôi xưng để typing message lần sau dùng đúng
      if (metadata.co_tham_xung) state.coThamXung = metadata.co_tham_xung;
    }
    // Thêm nút 🔊 TTS nếu có text
    if (fullText && state.ttsAvailable) addSpeakButton(botEl, fullText);
    if (!fullText && !metadata) contentEl.textContent = 'Dạ xin lỗi, cô chưa nhận được phản hồi. Bạn thử lại nhé 🙏';
  } catch(e) {
    hideTyping();
    const errEl = addBotBubble();
    errEl.querySelector('.bot-message-content').textContent = 'Dạ xin lỗi, có lỗi kết nối. Bạn thử lại nhé 🙏';
  }
  state.isLoading = false; toggleSendBtn();
}

function askQuestion(text) { sendMessage(text); }

// ══════════════════════════════════
// TTS (Text-to-Speech) — Nút 🔊
// ══════════════════════════════════
function addSpeakButton(botEl, text) {
  const bubble = botEl.querySelector('.bot-bubble');
  if (!bubble) return;
  const btn = document.createElement('button');
  btn.className = 'speak-btn';
  btn.innerHTML = '🔊';
  btn.title = 'Nghe Cô Thắm đọc';
  btn.setAttribute('aria-label', 'Nghe giọng nói');
  btn.onclick = () => speakText(btn, text);
  bubble.appendChild(btn);
}

async function speakText(btn, text) {
  if (btn.disabled) return;
  const orig = btn.innerHTML;
  btn.innerHTML = '⏳'; btn.disabled = true;
  try {
    const resp = await fetch('/api/tts/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!resp.ok) throw new Error('TTS error ' + resp.status);
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    // Dừng audio trước đó (nếu có)
    if (state.currentAudio) { state.currentAudio.pause(); state.currentAudio = null; }
    const audio = new Audio(url);
    state.currentAudio = audio;
    btn.innerHTML = '⏸️';
    audio.onended = () => { btn.innerHTML = '🔊'; btn.disabled = false; state.currentAudio = null; URL.revokeObjectURL(url); };
    audio.onerror = () => { btn.innerHTML = '❌'; setTimeout(() => { btn.innerHTML = '🔊'; btn.disabled = false; }, 2000); };
    audio.play();
  } catch(e) {
    console.error('[TTS]', e);
    btn.innerHTML = '❌'; setTimeout(() => { btn.innerHTML = orig; btn.disabled = false; }, 2000);
  }
}

// Kiểm tra TTS sidecar có sẵn không
async function checkTTSAvailability() {
  try {
    const resp = await fetch('/api/tts/health');
    const data = await resp.json();
    state.ttsAvailable = data.tts_available === true;
  } catch(e) { state.ttsAvailable = false; }
}

// ══════════════════════════════════
// INPUT & SIDEBAR
// ══════════════════════════════════
function autoResize() { const el = inputEl(); el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 100) + 'px'; }
function toggleSendBtn() { $('#send-btn').disabled = state.isLoading || !inputEl().value.trim(); }
function handleKeydown(e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(inputEl().value); } }
function toggleSidebar() { $('.sidebar').classList.toggle('open'); $('.overlay').classList.toggle('open'); }
function closeSidebar() { $('.sidebar').classList.remove('open'); $('.overlay').classList.remove('open'); }

function clearChat() {
  state.sessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
  state.messages = []; state.enrollmentId = null;
  chatArea().innerHTML = ''; state.hasWelcome = true; removeSuggestions();
  if (state.guestProfile) {
    const firstName = state.guestProfile.full_name.split(' ').pop();
    addBotGreeting(`Dạ ${firstName} ơi, mình bắt đầu cuộc trò chuyện mới nhé! 😊 ${firstName} muốn hỏi gì ạ?`);
  }
}

// ══════════════════════════════════
// INIT
// ══════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  const savedSession = sessionStorage.getItem('ufm_session');
  const savedProfile = sessionStorage.getItem('ufm_profile');
  if (savedSession && savedProfile) {
    state.sessionId = savedSession;
    state.guestProfile = JSON.parse(savedProfile);
    showChatScreen();
  }
  // Defer input listeners (only exist after chat screen shown)
  setTimeout(() => {
    const inp = inputEl();
    if (inp) { inp.addEventListener('input', () => { autoResize(); toggleSendBtn(); }); inp.addEventListener('keydown', handleKeydown); toggleSendBtn(); }
  }, 600);
  // Kiểm tra TTS sidecar
  checkTTSAvailability();
});
