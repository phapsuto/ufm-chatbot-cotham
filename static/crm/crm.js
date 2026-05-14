/**
 * CRM Dashboard — UFM Sau đại học
 * crm.js — Frontend logic: auth, data, charts, lead management
 */
const CRM = (() => {
    const API = '/api/crm';
    let token = sessionStorage.getItem('crm_token') || '';
    let currentLeadId = null;
    let currentPage = 1;
    let chartDaily = null, chartGrade = null, chartNganh = null;

    // ── Auth ─────────────────────────
    function headers() { return { 'Content-Type': 'application/json', 'X-CRM-Token': token }; }

    async function login(password) {
        try {
            const r = await fetch(`${API}/login`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password }),
            });
            const data = await r.json();
            if (data.success) {
                token = data.token;
                sessionStorage.setItem('crm_token', token);
                showApp();
            } else {
                document.getElementById('loginError').style.display = 'block';
            }
        } catch { document.getElementById('loginError').style.display = 'block'; }
    }

    function logout() {
        token = '';
        sessionStorage.removeItem('crm_token');
        document.getElementById('mainApp').style.display = 'none';
        document.getElementById('loginScreen').style.display = 'flex';
        document.getElementById('loginPassword').value = '';
    }

    function showApp() {
        document.getElementById('loginScreen').style.display = 'none';
        document.getElementById('mainApp').style.display = 'flex';
        loadDashboard();
    }

    // ── Navigation ───────────────────
    function switchPage(pageId) {
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        document.getElementById('page' + pageId.charAt(0).toUpperCase() + pageId.slice(1)).classList.add('active');
        document.querySelector(`[data-page="${pageId}"]`).classList.add('active');
        if (pageId === 'dashboard') loadDashboard();
        if (pageId === 'leads') loadLeads();
    }

    // ── Dashboard ────────────────────
    async function loadDashboard() {
        try {
            const r = await fetch(`${API}/dashboard/stats`, { headers: headers() });
            if (r.status === 401 || r.status === 403) { logout(); return; }
            const d = await r.json();

            document.getElementById('kpiTotal').textContent = d.total_leads;
            document.getElementById('kpiHot').textContent = d.hot_leads;
            document.getElementById('kpiInterested').textContent = d.interested;
            document.getElementById('kpiEnrolled').textContent = d.enrolled;
            document.getElementById('kpiNewToday').textContent = `+${d.new_today} hôm nay`;

            renderCharts(d);
            renderHotLeads(d.hot_uncontacted || []);
        } catch (e) { console.error('Dashboard error:', e); }
    }

    function renderCharts(data) {
        // Daily leads chart
        const dailyCtx = document.getElementById('chartDaily').getContext('2d');
        if (chartDaily) chartDaily.destroy();
        const daily = data.daily_leads || [];
        chartDaily = new Chart(dailyCtx, {
            type: 'bar',
            data: {
                labels: daily.map(d => d[0].slice(5)),
                datasets: [{ label: 'Leads mới', data: daily.map(d => d[1]),
                    backgroundColor: '#003087', borderRadius: 6, barPercentage: 0.6 }]
            },
            options: { responsive: true, plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true, ticks: { stepSize: 1 } } } }
        });

        // Grade distribution
        const gradeCtx = document.getElementById('chartGrade').getContext('2d');
        if (chartGrade) chartGrade.destroy();
        const gd = data.grade_distribution || {};
        chartGrade = new Chart(gradeCtx, {
            type: 'doughnut',
            data: {
                labels: ['🔥 A', '⭐ B', '💡 C', '❄️ D'],
                datasets: [{ data: [gd.A||0, gd.B||0, gd.C||0, gd.D||0],
                    backgroundColor: ['#ef4444','#f59e0b','#3b82f6','#94a3b8'], borderWidth: 0 }]
            },
            options: { responsive: true, plugins: { legend: { position: 'bottom', labels: { padding: 12, font: { size: 12 } } } } }
        });

        // Top ngành
        const nganhCtx = document.getElementById('chartNganh').getContext('2d');
        if (chartNganh) chartNganh.destroy();
        const tn = data.top_nganh || [];
        chartNganh = new Chart(nganhCtx, {
            type: 'bar',
            data: {
                labels: tn.map(n => n[0]),
                datasets: [{ label: 'Lượt quan tâm', data: tn.map(n => n[1]),
                    backgroundColor: '#1a4da0', borderRadius: 6, barPercentage: 0.5 }]
            },
            options: { responsive: true, indexAxis: 'y', plugins: { legend: { display: false } },
                scales: { x: { beginAtZero: true, ticks: { stepSize: 1 } } } }
        });
    }

    function renderHotLeads(leads) {
        const tbody = document.querySelector('#hotLeadsTable tbody');
        const noLeads = document.getElementById('noHotLeads');
        tbody.innerHTML = '';
        if (!leads.length) { noLeads.style.display = 'block'; return; }
        noLeads.style.display = 'none';
        leads.forEach(l => {
            tbody.innerHTML += `<tr>
                <td><strong>${esc(l.ho_ten)}</strong></td>
                <td>${scoreHtml(l.lead_score)}</td>
                <td>${(l.nganh||[]).join(', ')||'—'}</td>
                <td>${esc(l.contact)}</td>
                <td>${l.thoi_gian_chat_phut} phút</td>
            </tr>`;
        });
    }

    // ── Leads List ───────────────────
    async function loadLeads(page = 1) {
        currentPage = page;
        const params = new URLSearchParams({ page, per_page: 20 });
        const search = document.getElementById('filterSearch')?.value;
        const grade = document.getElementById('filterGrade')?.value;
        const status = document.getElementById('filterStatus')?.value;
        if (search) params.set('search', search);
        if (grade) params.set('grade', grade);
        if (status) params.set('status', status);

        try {
            const r = await fetch(`${API}/leads?${params}`, { headers: headers() });
            if (r.status === 401 || r.status === 403) { logout(); return; }
            const d = await r.json();
            renderLeadsTable(d.leads, d.page, d.total);
            renderPagination(d.page, d.pages);
        } catch (e) { console.error('Leads error:', e); }
    }

    function renderLeadsTable(leads, page, total) {
        const tbody = document.querySelector('#leadsTable tbody');
        tbody.innerHTML = '';
        if (!leads.length) { tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;padding:24px;color:#94a3b8">Chưa có leads nào</td></tr>'; return; }
        leads.forEach((l, i) => {
            const idx = (page - 1) * 20 + i + 1;
            const gradeClass = `badge-${l.lead_grade?.toLowerCase()}`;
            tbody.innerHTML += `<tr>
                <td>${idx}</td>
                <td><strong>${esc(l.ho_ten)}</strong></td>
                <td>${l.tuoi || '—'}</td>
                <td>${(l.nganh_hoi_toi||[]).slice(0,2).join(', ')||'—'}</td>
                <td>${scoreHtml(l.lead_score)}</td>
                <td style="font-weight:600">${l.enrollment_probability_pct||'0%'}</td>
                <td><span class="badge ${gradeClass}">${l.lead_grade}</span></td>
                <td>${esc(l.contact).slice(0,20)}</td>
                <td>${l.so_tin_nhan||0} tin | ${l.thoi_gian_chat_phut||0}p</td>
                <td><span class="badge-status ${l.status}">${statusLabel(l.status)}</span></td>
                <td><button class="btn-view" onclick="CRM.openLead('${l.lead_id}')">Xem</button></td>
            </tr>`;
        });
    }

    function renderPagination(page, pages) {
        const el = document.getElementById('pagination');
        el.innerHTML = '';
        if (pages <= 1) return;
        for (let i = 1; i <= pages; i++) {
            const btn = document.createElement('button');
            btn.textContent = i;
            if (i === page) btn.classList.add('active');
            btn.onclick = () => loadLeads(i);
            el.appendChild(btn);
        }
    }

    // ── Lead Detail ──────────────────
    async function openLead(leadId) {
        currentLeadId = leadId;
        try {
            const r = await fetch(`${API}/leads/${leadId}`, { headers: headers() });
            const l = await r.json();
            document.getElementById('modalName').textContent = l.ho_ten;
            document.getElementById('modalGrade').textContent = l.lead_grade;
            document.getElementById('modalGrade').className = `badge badge-${l.lead_grade?.toLowerCase()}`;
            document.getElementById('modalStatus').textContent = statusLabel(l.status);
            document.getElementById('modalStatus').className = `badge-status ${l.status}`;

            document.getElementById('modalAge').textContent = l.tuoi || '—';
            document.getElementById('modalEdu').textContent = l.trinh_do || '—';
            document.getElementById('modalContact').textContent = l.contact || '—';
            document.getElementById('modalDate').textContent = (l.created_at || '').slice(0, 10);

            // Score
            const scoreEl = document.getElementById('modalScore');
            scoreEl.textContent = l.lead_score;
            const circle = document.getElementById('modalScoreCircle');
            if (l.lead_score >= 75) circle.style.background = 'linear-gradient(135deg,#dc2626,#ef4444)';
            else if (l.lead_score >= 55) circle.style.background = 'linear-gradient(135deg,#d97706,#f59e0b)';
            else if (l.lead_score >= 35) circle.style.background = 'linear-gradient(135deg,#2563eb,#3b82f6)';
            else circle.style.background = 'linear-gradient(135deg,#64748b,#94a3b8)';

            document.getElementById('modalProb').textContent = l.enrollment_probability_pct || '0%';

            // Breakdown
            renderBreakdown(l.score_breakdown || {});

            // AI
            const aiSection = document.getElementById('aiSection');
            if (l.nhan_xet_ngan || l.goi_y_follow_up || l.rao_can) {
                aiSection.style.display = 'block';
                document.getElementById('aiNhanXet').textContent = l.nhan_xet_ngan ? `💡 Nhận xét: ${l.nhan_xet_ngan}` : '';
                document.getElementById('aiFollowUp').textContent = l.goi_y_follow_up ? `📞 Gợi ý: ${l.goi_y_follow_up}` : '';
                document.getElementById('aiRaoCan').textContent = l.rao_can ? `⚠️ Rào cản: ${l.rao_can}` : '';
            } else { aiSection.style.display = 'none'; }

            // Chat stats
            document.getElementById('modalMsgCount').textContent = l.so_tin_nhan || 0;
            document.getElementById('modalChatTime').textContent = l.thoi_gian_chat_phut || 0;
            document.getElementById('modalNganh').textContent = (l.nganh_hoi_toi || []).join(', ') || '—';

            // Actions
            document.getElementById('actionStatus').value = l.status || '';
            document.getElementById('actionAssignee').value = l.assigned_to || '';

            // Notes
            renderNotes(l.notes || []);

            document.getElementById('leadModal').style.display = 'flex';
        } catch (e) { console.error('Lead detail error:', e); }
    }

    function renderBreakdown(bd) {
        const el = document.getElementById('modalBreakdown');
        el.innerHTML = '';
        const labels = { profile: 'Hồ sơ học viên', engagement: 'Tương tác chat', action: 'Hành động cụ thể' };
        for (const [key, group] of Object.entries(bd)) {
            let html = `<div class="breakdown-col"><h4>${labels[key]||key} [${group.diem}/${group.toi_da}]</h4>`;
            for (const item of (group.chi_tiet || [])) {
                html += `<div class="breakdown-item pass">✅ ${esc(item.ly_do)} (+${item.diem})</div>`;
            }
            if (!(group.chi_tiet || []).length) {
                html += `<div class="breakdown-item fail">— chưa có dữ liệu</div>`;
            }
            html += '</div>';
            el.innerHTML += html;
        }
    }

    function renderNotes(notes) {
        const el = document.getElementById('notesList');
        el.innerHTML = '';
        notes.slice().reverse().forEach(n => {
            el.innerHTML += `<div class="note-entry">
                <strong>${esc(n.author)}</strong><small>${(n.timestamp||'').slice(0,16).replace('T',' ')}</small>
                <p style="margin-top:4px">${esc(n.content)}</p>
            </div>`;
        });
    }

    function closeModal() { document.getElementById('leadModal').style.display = 'none'; currentLeadId = null; }

    async function saveActions() {
        if (!currentLeadId) return;
        const status = document.getElementById('actionStatus').value;
        const assigned_to = document.getElementById('actionAssignee').value;
        try {
            await fetch(`${API}/leads/${currentLeadId}`, {
                method: 'PATCH', headers: headers(),
                body: JSON.stringify({ status: status || null, assigned_to }),
            });
            openLead(currentLeadId); // refresh
        } catch (e) { console.error(e); }
    }

    async function addNote() {
        if (!currentLeadId) return;
        const content = document.getElementById('noteContent').value.trim();
        if (!content) return;
        try {
            await fetch(`${API}/leads/${currentLeadId}/notes`, {
                method: 'POST', headers: headers(),
                body: JSON.stringify({ author: 'Nhân viên CRM', content }),
            });
            document.getElementById('noteContent').value = '';
            openLead(currentLeadId); // refresh
        } catch (e) { console.error(e); }
    }

    // ── Export ────────────────────────
    async function exportCSV(grade, status) {
        const params = new URLSearchParams();
        if (grade) params.set('grade', grade);
        if (status) params.set('status', status);
        try {
            const r = await fetch(`${API}/export/csv?${params}`, { headers: headers() });
            const blob = await r.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = 'ufm_crm_leads.csv'; a.click();
            URL.revokeObjectURL(url);
        } catch (e) { console.error(e); }
    }

    // ── Helpers ───────────────────────
    function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
    function scoreHtml(score) {
        const color = score >= 75 ? '#ef4444' : score >= 55 ? '#f59e0b' : score >= 35 ? '#3b82f6' : '#94a3b8';
        return `<span class="score-bar"><span class="score-bar-fill" style="width:${score}%;background:${color}"></span></span><span class="score-text" style="color:${color}">${score}</span>`;
    }
    function statusLabel(s) {
        const map = { new:'Mới', hot_lead:'Hot Lead', interested:'Quan tâm', follow_up:'Follow up', enrolled:'Đã ĐK', lost:'Bỏ qua' };
        return map[s] || s || 'Mới';
    }

    // ── Init ─────────────────────────
    function init() {
        // Login form
        document.getElementById('loginForm').addEventListener('submit', e => {
            e.preventDefault();
            login(document.getElementById('loginPassword').value);
        });
        // Logout
        document.getElementById('logoutBtn').addEventListener('click', logout);
        // Navigation
        document.querySelectorAll('.nav-item').forEach(n => {
            n.addEventListener('click', e => { e.preventDefault(); switchPage(n.dataset.page); });
        });
        // Filters
        let filterTimer;
        const filterFn = () => { clearTimeout(filterTimer); filterTimer = setTimeout(() => loadLeads(1), 300); };
        document.getElementById('filterSearch')?.addEventListener('input', filterFn);
        document.getElementById('filterGrade')?.addEventListener('change', filterFn);
        document.getElementById('filterStatus')?.addEventListener('change', filterFn);
        document.getElementById('btnExportCsv')?.addEventListener('click', () => exportCSV());

        // Auto-login if token exists
        if (token) showApp();
    }

    document.addEventListener('DOMContentLoaded', init);

    return { login, logout, openLead, closeModal, saveActions, addNote, exportCSV, loadLeads };
})();
