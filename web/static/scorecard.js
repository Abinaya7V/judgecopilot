const el = (sel) => document.querySelector(sel);
const codeForm = el("#codeForm");
const accessCodeInput = el("#accessCodeInput");
const lookupError = el("#lookupError");
const resultPanel = el("#resultPanel");
const lookupPanel = el("#lookupPanel");
const lookupBtn = el("#lookupBtn");

codeForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = accessCodeInput.value.trim().toUpperCase();
  if (!code) return;
  
  lookupError.style.display = "none";
  lookupBtn.disabled = true;
  lookupBtn.textContent = "Looking up...";
  
  try {
    const res = await fetch(`/api/scorecard/${code}`);
    if (res.status === 404) {
      lookupError.textContent = "Access code not found or invalid.";
      lookupError.style.display = "block";
      return;
    }
    if (!res.ok) {
      lookupError.textContent = "An error occurred fetching the scorecard.";
      lookupError.style.display = "block";
      return;
    }
    
    const data = await res.json();
    renderScorecard(data);
    lookupPanel.style.display = "none";
    resultPanel.style.display = "block";
  } catch (err) {
    lookupError.textContent = "Network error connecting to the server.";
    lookupError.style.display = "block";
  } finally {
    lookupBtn.disabled = false;
    lookupBtn.textContent = "View Result";
  }
});

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderScorecard(d) {
  let content = `
    <div class="case-header">
      <div class="eyebrow">Submission Scorecard</div>
      <h2>${escapeHtml(d.project_title)}</h2>
      <div class="meta">${escapeHtml(d.team_name)}</div>
    </div>
  `;
  
  if (d.status === "not yet evaluated") {
    content += `
      <div class="submission-meta-box" style="text-align: center; padding: 40px;">
        <h3 style="font-family: var(--serif); color: var(--ink);">Not Yet Evaluated</h3>
        <p style="color: var(--ink-soft);">Your submission has been received but scoring is not yet complete. Please check back later.</p>
      </div>
    `;
  } else {
    content += `
      <div class="overall-score">
        <span class="num">${d.overall_score}</span>
        <span class="label">/ 100 overall score</span>
      </div>
    `;
    
    if (d.similarity_notice) {
      content += `
        <div class="flags-box">
          <h3>Notice</h3>
          <ul><li>${escapeHtml(d.similarity_notice)}</li></ul>
        </div>
      `;
    }
    
    content += `
      <div class="rubric-section">
        <div class="section-title">Rubric scores</div>
        ${d.dimension_scores.map((ds) => `
          <div class="dim-row">
            <div class="dim-top">
              <span class="dim-name">${escapeHtml(ds.label)}</span>
              <span class="dim-score">${ds.score}/10</span>
            </div>
            <div class="bar-track"><div class="bar-fill" style="width:${ds.score * 10}%"></div></div>
            <div class="dim-justification" style="white-space: pre-wrap;">${escapeHtml(ds.justification)}</div>
          </div>
        `).join("")}
      </div>
    `;
  }
  
  content += `
    <div style="text-align: center; margin-top: 40px;">
      <button class="btn-secondary" onclick="location.reload()">Look up another code</button>
    </div>
  `;
  
  resultPanel.innerHTML = content;
}
