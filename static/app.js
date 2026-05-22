(function () {
  const page = document.querySelector('.annotate-page');
  if (!page) return;

  const conversationId = page.dataset.conversationId;
  const doctorBasePath = page.dataset.doctorBasePath || '/doctor';
  const editedText = document.getElementById('edited-text');
  const autosaveStatus = document.getElementById('autosave-status');
  const submitStatus = document.getElementById('submit-status');
  const consentCheckbox = document.getElementById('consent-checkbox');
  const baselineChineseTextEl = document.getElementById('baseline-chinese-text');
  const editedHighlightPreview = document.getElementById('edited-highlight-preview');
  const originalHighlightPreview = document.getElementById('original-highlight-preview');

  const submitBtn = document.getElementById('submit-btn');
  const discardBtn = document.getElementById('discard-btn');

  let debounceTimer = null;
  let autosaveTimer = null;
  let renderFrame = null;
  let isSubmitted = submitStatus.textContent.toLowerCase().includes('current status: submitted');
  let lastSavedValue = editedText.value || '';
  const originalChineseText = baselineChineseTextEl ? baselineChineseTextEl.textContent : '';
  const MAX_DP_CELLS = 1200000;

  async function postJson(url, payload) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || 'Request failed');
    }
    return data;
  }

  function postJsonBeacon(url, payload) {
    if (!navigator.sendBeacon) return false;
    const blob = new Blob([JSON.stringify(payload || {})], { type: 'application/json' });
    return navigator.sendBeacon(url, blob);
  }

  function setSaving() {
    autosaveStatus.textContent = 'Saving...';
  }

  function setSaved(timeText) {
    autosaveStatus.textContent = `Saved at ${timeText}`;
  }

  function pushMergedRange(ranges, start, end) {
    if (end <= start) return;
    const last = ranges[ranges.length - 1];
    if (!last || start > last.end) {
      ranges.push({ start, end });
      return;
    }
    last.end = Math.max(last.end, end);
  }

  function computeChangedRangesHeuristic(originalText, editedValue) {
    const originalRanges = [];
    const editedRanges = [];
    const insertionCountByPos = new Array(originalText.length + 1).fill(0);
    const lookahead = 80;
    let i = 0;
    let j = 0;

    while (i < originalText.length && j < editedValue.length) {
      if (originalText[i] === editedValue[j]) {
        i += 1;
        j += 1;
        continue;
      }

      let aligned = false;
      for (let offset = 1; offset <= lookahead; offset += 1) {
        const oi = i + offset;
        const ej = j + offset;

        if (j + offset <= editedValue.length && originalText[i] === editedValue[j + offset]) {
          pushMergedRange(editedRanges, j, j + offset);
          insertionCountByPos[i] += offset;
          j += offset;
          aligned = true;
          break;
        }

        if (i + offset <= originalText.length && originalText[i + offset] === editedValue[j]) {
          pushMergedRange(originalRanges, i, i + offset);
          i += offset;
          aligned = true;
          break;
        }

        if (
          oi < originalText.length &&
          ej < editedValue.length &&
          originalText[oi] === editedValue[ej]
        ) {
          pushMergedRange(originalRanges, i, oi);
          pushMergedRange(editedRanges, j, ej);
          i = oi;
          j = ej;
          aligned = true;
          break;
        }
      }

      if (!aligned) {
        pushMergedRange(originalRanges, i, i + 1);
        pushMergedRange(editedRanges, j, j + 1);
        i += 1;
        j += 1;
      }
    }

    if (i < originalText.length) {
      pushMergedRange(originalRanges, i, originalText.length);
    }
    if (j < editedValue.length) {
      pushMergedRange(editedRanges, j, editedValue.length);
      insertionCountByPos[i] += editedValue.length - j;
    }

    const originalChanged = new Array(originalText.length).fill(false);
    originalRanges.forEach((range) => {
      for (let idx = range.start; idx < range.end; idx += 1) {
        originalChanged[idx] = true;
      }
    });

    const insertionMarkers = [];
    insertionCountByPos.forEach((count, pos) => {
      if (count <= 0) return;
      const leftChanged = pos > 0 ? originalChanged[pos - 1] : false;
      const rightChanged = pos < originalChanged.length ? originalChanged[pos] : false;
      if (!leftChanged && !rightChanged) {
        insertionMarkers.push({ pos, count });
      }
    });

    return { originalRanges, editedRanges, insertionMarkers };
  }

  function boolsToRanges(flags) {
    const ranges = [];
    let i = 0;
    while (i < flags.length) {
      if (!flags[i]) {
        i += 1;
        continue;
      }
      let j = i + 1;
      while (j < flags.length && flags[j]) j += 1;
      ranges.push({ start: i, end: j });
      i = j;
    }
    return ranges;
  }

  function computeChangedRangesExact(originalText, editedValue) {
    const n = originalText.length;
    const m = editedValue.length;
    const rowSize = m + 1;
    const dp = new Uint32Array((n + 1) * (m + 1));
    const insertionCountByPos = new Array(n + 1).fill(0);

    for (let i = 1; i <= n; i += 1) {
      for (let j = 1; j <= m; j += 1) {
        const idx = i * rowSize + j;
        if (originalText[i - 1] === editedValue[j - 1]) {
          dp[idx] = dp[(i - 1) * rowSize + (j - 1)] + 1;
        } else {
          const up = dp[(i - 1) * rowSize + j];
          const left = dp[i * rowSize + (j - 1)];
          dp[idx] = up >= left ? up : left;
        }
      }
    }

    const originalChanged = new Array(n).fill(false);
    const editedChanged = new Array(m).fill(false);

    let i = n;
    let j = m;
    while (i > 0 && j > 0) {
      if (originalText[i - 1] === editedValue[j - 1]) {
        i -= 1;
        j -= 1;
      } else {
        const up = dp[(i - 1) * rowSize + j];
        const left = dp[i * rowSize + (j - 1)];
        if (up >= left) {
          originalChanged[i - 1] = true;
          i -= 1;
        } else {
          editedChanged[j - 1] = true;
          insertionCountByPos[i] += 1;
          j -= 1;
        }
      }
    }

    while (i > 0) {
      originalChanged[i - 1] = true;
      i -= 1;
    }
    while (j > 0) {
      editedChanged[j - 1] = true;
      insertionCountByPos[0] += 1;
      j -= 1;
    }

    const insertionMarkers = [];
    insertionCountByPos.forEach((count, pos) => {
      if (count <= 0) return;
      const leftChanged = pos > 0 ? originalChanged[pos - 1] : false;
      const rightChanged = pos < originalChanged.length ? originalChanged[pos] : false;
      // Show marker only for pure insertion points (no deletion/replacement touching this boundary).
      if (!leftChanged && !rightChanged) {
        insertionMarkers.push({ pos, count });
      }
    });

    return {
      originalRanges: boolsToRanges(originalChanged),
      editedRanges: boolsToRanges(editedChanged),
      insertionMarkers,
    };
  }

  function computeChangedRanges(originalText, editedValue) {
    if (originalText.length * editedValue.length <= MAX_DP_CELLS) {
      return computeChangedRangesExact(originalText, editedValue);
    }
    return computeChangedRangesHeuristic(originalText, editedValue);
  }

  function escapeHtml(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function renderHighlightedText(text, classByIndex) {
    if (!text.length) return '';
    let html = '';
    let start = 0;

    while (start < text.length) {
      const cls = classByIndex[start];
      let end = start + 1;
      while (end < text.length && classByIndex[end] === cls) end += 1;

      const chunk = escapeHtml(text.slice(start, end));
      if (cls) {
        html += `<span class="${cls}">${chunk}</span>`;
      } else {
        html += chunk;
      }
      start = end;
    }
    return html;
  }

  function renderOriginalWithInsertMarkers(text, classByIndex, insertionMarkers) {
    const markersByPos = new Map();
    (insertionMarkers || []).forEach((m) => {
      markersByPos.set(m.pos, (markersByPos.get(m.pos) || 0) + m.count);
    });

    let html = '';
    for (let idx = 0; idx <= text.length; idx += 1) {
      const markerCount = markersByPos.get(idx) || 0;
      if (markerCount > 0) {
        // Show highlighted blank gap to indicate inserted content in edited text at this position.
        html += `<span class="hl-yellow insert-gap">${'&nbsp;'.repeat(markerCount)}</span>`;
      }
      if (idx < text.length) {
        const cls = classByIndex[idx];
        const chunk = escapeHtml(text[idx]);
        html += cls ? `<span class="${cls}">${chunk}</span>` : chunk;
      }
    }
    return html;
  }

  function renderHighlights() {
    if (!editedHighlightPreview || !originalHighlightPreview) return;
    const editedValue = editedText.value || '';
    const changed = computeChangedRanges(originalChineseText, editedValue);

    const editedClasses = new Array(editedValue.length).fill('');
    changed.editedRanges.forEach((range) => {
      for (let i = range.start; i < range.end; i += 1) {
        if (i >= 0 && i < editedClasses.length) editedClasses[i] = 'hl-red';
      }
    });

    const originalClasses = new Array(originalChineseText.length).fill('');
    changed.originalRanges.forEach((range) => {
      for (let i = range.start; i < range.end; i += 1) {
        if (i >= 0 && i < originalClasses.length) originalClasses[i] = 'hl-yellow';
      }
    });

    editedHighlightPreview.innerHTML = renderHighlightedText(editedValue, editedClasses);
    originalHighlightPreview.innerHTML = renderOriginalWithInsertMarkers(
      originalChineseText,
      originalClasses,
      changed.insertionMarkers
    );
  }

  function queueRenderHighlights() {
    if (renderFrame !== null) {
      cancelAnimationFrame(renderFrame);
    }
    renderFrame = requestAnimationFrame(() => {
      renderFrame = null;
      renderHighlights();
    });
  }

  async function saveDraft() {
    if (isSubmitted) return;
    setSaving();
    try {
      const data = await postJson(`${doctorBasePath}/submission/${conversationId}/save-draft`, {
        translated_text_edited: editedText.value,
      });
      lastSavedValue = editedText.value;
      setSaved(data.last_saved_at);
    } catch (err) {
      autosaveStatus.textContent = `Save failed: ${err.message}`;
    }
  }

  function debounceSave() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(saveDraft, 800);
  }

  editedText.addEventListener('input', function () {
    if (isSubmitted) return;
    autosaveStatus.textContent = 'Unsaved changes';
    queueRenderHighlights();
    debounceSave();
  });

  editedText.addEventListener('blur', function () {
    if (isSubmitted) return;
    if (editedText.value === lastSavedValue) return;
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    saveDraft();
  });

  autosaveTimer = setInterval(saveDraft, 10000);

  function lockSubmittedUi() {
    isSubmitted = true;
    if (autosaveTimer) clearInterval(autosaveTimer);
    editedText.setAttribute('disabled', 'disabled');
    discardBtn.setAttribute('disabled', 'disabled');
  }

  submitBtn.addEventListener('click', async function () {
    if (isSubmitted) return;
    if (!consentCheckbox.checked) {
      alert('Consent checkbox is required before submit.');
      return;
    }

    try {
      const data = await postJson(`${doctorBasePath}/submission/${conversationId}/submit`, {
        consent_confirmed: true,
      });
      submitStatus.textContent = `Current status: ${data.status} (submitted at ${data.submitted_at})`;
      autosaveStatus.textContent = 'Submission complete';
      alert(`Submission successful ??\nSubmitted at ${data.submitted_at}`);
      lockSubmittedUi();
      window.location.href = `${doctorBasePath}/tasks`;
    } catch (err) {
      alert(`Submit failed: ${err.message}`);
    }
  });

  discardBtn.addEventListener('click', async function () {
    const ok = confirm('Discard current draft for this conversation?');
    if (!ok) return;

    try {
      const data = await postJson(`${doctorBasePath}/submission/${conversationId}/discard`, {});
      editedText.value = data.translated_text_edited;
      lastSavedValue = editedText.value;
      submitStatus.textContent = `Current status: ${data.status}`;
      setSaved(data.last_saved_at);
      queueRenderHighlights();
    } catch (err) {
      alert(`Discard failed: ${err.message}`);
    }
  });

  queueRenderHighlights();
  if (isSubmitted) {
    lockSubmittedUi();
  }

  window.addEventListener('pagehide', function () {
    if (isSubmitted) return;
    if (editedText.value === lastSavedValue) return;
    postJsonBeacon(`${doctorBasePath}/submission/${conversationId}/save-draft`, {
      translated_text_edited: editedText.value,
    });
  });
})();
