async function loadJuryData() {
    try {
        const [overview, leaderboard, similarity] = await Promise.all([
            fetch('/api/jury/overview').then(r => r.json()),
            fetch('/api/jury/leaderboard').then(r => r.json()),
            fetch('/api/batch/similarity').then(r => r.json())
        ]);

        renderOverview(overview);
        renderLeaderboard(leaderboard);
        renderSimilarity(similarity);
    } catch (e) {
        console.error("Failed to load jury data", e);
    }
}

function renderOverview(data) {
    const stats = document.getElementById('progressStats');
    stats.innerHTML = `
        <div class="stat-card"><div class="value">${data.ingested}</div><div class="label">Ingested</div></div>
        <div class="stat-card"><div class="value">${data.scored}</div><div class="label">Scored</div></div>
        <div class="stat-card"><div class="value">${data.unscored}</div><div class="label">Unscored</div></div>
    `;
}

function renderLeaderboard(data) {
    const tbody = document.querySelector('#leaderboardTable tbody');
    tbody.innerHTML = '';
    
    data.forEach(row => {
        const tr = document.createElement('tr');
        tr.className = 'clickable-row';
        tr.onclick = () => {
            const exp = document.getElementById(`exp-${row.id}`);
            if (exp.classList.contains('active')) {
                exp.classList.remove('active');
            } else {
                // close others
                document.querySelectorAll('.expanded-row').forEach(el => el.classList.remove('active'));
                exp.classList.add('active');
            }
        };

        let flagsHtml = '';
        if (row.disagreement_flags && row.disagreement_flags.length > 0) {
            flagsHtml += `<span class="badge disagreement">Disagreement: ${row.disagreement_flags.join(', ')}</span>`;
        }
        if (row.similarity_flags && row.similarity_flags.length > 0) {
            flagsHtml += `<span class="badge similarity">Similarity Flagged</span>`;
        }

        tr.innerHTML = `
            <td>#${row.rank}</td>
            <td><strong>${row.team_name}</strong><br><small style="color:var(--text-dim)">${row.project_title}</small></td>
            <td>${row.calibrated_total}</td>
            <td>${row.weighted_total}</td>
            <td>${row.judges_scored}</td>
            <td>${flagsHtml}</td>
        `;

        const expTr = document.createElement('tr');
        expTr.id = `exp-${row.id}`;
        expTr.className = 'expanded-row';
        
        let judgesHtml = '';
        for (const [j_id, res] of Object.entries(row.per_judge_results)) {
            judgesHtml += `<div class="judge-column">
                <h4 style="margin-top:0">Judge: ${j_id}</h4>
                <p><strong>Score: ${res.weighted_total}</strong></p>
                ${res.dimension_scores.map(ds => `
                    <div style="margin-bottom:0.5rem">
                        <strong>${ds.label}: ${ds.score}/10</strong><br>
                        <small>${ds.justification}</small>
                    </div>
                `).join('')}
            </div>`;
        }

        expTr.innerHTML = `
            <td colspan="6" class="expanded-content">
                <div style="display:flex; overflow-x:auto;">
                    ${judgesHtml}
                </div>
            </td>
        `;

        tbody.appendChild(tr);
        tbody.appendChild(expTr);
    });
}

function renderSimilarity(data) {
    const panel = document.getElementById('similarityPanel');
    if (!data || data.length === 0) {
        panel.innerHTML = '<p style="color: var(--text-dim);">No similarity flags found.</p>';
        return;
    }
    
    panel.innerHTML = data.map(m => `
        <div style="background: var(--bg-subtle); padding: 1rem; border-radius: 6px; margin-bottom: 1rem;">
            <strong>${m.team_a_name} &harr; ${m.team_b_name}</strong>
            <p style="margin: 0.5rem 0 0 0; font-size: 0.9rem;">
                Idea Score: ${m.idea_score.toFixed(2)} | Code Score: ${m.code_score.toFixed(2)}<br>
                Matched fields: <span class="badge similarity">${m.matched_fields.join(', ')}</span>
            </p>
        </div>
    `).join('');
}

document.getElementById('exportBtn').addEventListener('click', async () => {
    const res = await fetch('/api/jury/export');
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'jury_export.json';
    a.click();
    window.URL.revokeObjectURL(url);
});

loadJuryData();
