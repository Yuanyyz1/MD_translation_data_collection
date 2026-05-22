(function () {
  const workspace = document.querySelector('.doctor-workspace');
  if (!workspace) return;

  const doctorBasePath = workspace.dataset.doctorBasePath || '/doctor';
  const datasetName = workspace.dataset.datasetName || '';
  const workspaceCaptureRoot = document.querySelector('.workspace-capture-root');
  const workspaceBackLink = document.querySelector('.workspace-back-link');
  const workspaceSubmitBtn = workspace.querySelector('.workspace-submit-btn');
  const workspaceSubmitStatus = workspace.querySelector('.workspace-submit-status');
  const workspaceModifiedCount = workspace.querySelector('.workspace-modified-count');
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

  function escapeXml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&apos;');
  }

  function copyComputedStyles(sourceNode, clonedNode) {
    if (!(sourceNode instanceof Element) || !(clonedNode instanceof Element)) {
      return;
    }

    const computed = window.getComputedStyle(sourceNode);
    const styleText = Array.from(computed)
      .map((prop) => `${prop}:${computed.getPropertyValue(prop)};`)
      .join('');
    clonedNode.setAttribute('style', styleText);

    if (sourceNode instanceof HTMLTextAreaElement) {
      clonedNode.textContent = sourceNode.value;
    } else if (sourceNode instanceof HTMLInputElement) {
      clonedNode.setAttribute('value', sourceNode.value);
      if (sourceNode.checked) {
        clonedNode.setAttribute('checked', 'checked');
      } else {
        clonedNode.removeAttribute('checked');
      }
    } else if (sourceNode instanceof HTMLSelectElement) {
      clonedNode.setAttribute('value', sourceNode.value);
    }

    const sourceChildren = Array.from(sourceNode.childNodes);
    const clonedChildren = Array.from(clonedNode.childNodes);
    for (let i = 0; i < sourceChildren.length; i += 1) {
      copyComputedStyles(sourceChildren[i], clonedChildren[i]);
    }
  }

  async function captureElementAsPngDataUrl(element) {
    if (!element) {
      throw new Error('Workspace capture area was not found.');
    }

    const rect = element.getBoundingClientRect();
    const width = Math.max(Math.ceil(rect.width), 1);
    const height = Math.max(Math.ceil(rect.height), 1);
    const cloned = element.cloneNode(true);
    copyComputedStyles(element, cloned);

    const serialized = new XMLSerializer().serializeToString(cloned);
    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
        <foreignObject width="100%" height="100%">${serialized}</foreignObject>
      </svg>
    `;
    const svgUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;

    const image = new Image();
    image.decoding = 'async';

    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () => reject(new Error('Could not render screenshot image.'));
      image.src = svgUrl;
    });

    const scale = Math.min(Math.max(window.devicePixelRatio || 1, 2), 3);
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(Math.floor(width * scale), 1);
    canvas.height = Math.max(Math.floor(height * scale), 1);

    const context = canvas.getContext('2d');
    if (!context) {
      throw new Error('Canvas is not available in this browser.');
    }

    context.scale(scale, scale);
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = 'high';
    context.fillStyle = '#f5f6f8';
    context.fillRect(0, 0, width, height);
    context.drawImage(image, 0, 0, width, height);
    return canvas.toDataURL('image/png');
  }

  async function uploadWorkspaceScreenshot() {
    if (!datasetName) {
      throw new Error('Dataset name is missing.');
    }
    const imageBase64 = await captureElementAsPngDataUrl(workspaceCaptureRoot || workspace);
    await postJson(`${doctorBasePath}/workspace-screenshot`, {
      dataset_name: datasetName,
      image_base64: imageBase64,
    });
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

        if (oi < originalText.length && ej < editedValue.length && originalText[oi] === editedValue[ej]) {
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
      html += cls ? `<span class="${cls}">${chunk}</span>` : chunk;
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

  function setupConversationEditor(item) {
    const conversationId = item.dataset.conversationId;
    const highlightEnabled = item.dataset.highlightEnabled !== 'false';
    const editedText = item.querySelector('.edited-text');
    const autosaveStatus = item.querySelector('.autosave-status');
    const submitStatus = item.querySelector('.submit-status');
    const baselineChineseTextEl = item.querySelector('.baseline-chinese-text');
    const originalChineseHighlight = item.querySelector('.original-chinese-highlight');
    const discardBtn = item.querySelector('.discard-btn');

    if (!conversationId || !editedText || !autosaveStatus || !submitStatus) {
      return;
    }

    if (highlightEnabled && (!baselineChineseTextEl || !originalChineseHighlight)) {
      return;
    }

    const originalChineseText = baselineChineseTextEl ? baselineChineseTextEl.textContent || '' : '';
    let isSubmitted = item.dataset.status === 'submitted';
    let renderFrame = null;
    let autosaveTimer = null;
    let lastSavedValue = editedText.value || '';
    let saveInFlight = false;
    let saveQueued = false;

    function setSaving() {
      autosaveStatus.textContent = 'Saving...';
    }

    function setSaved(timeText) {
      autosaveStatus.textContent = `Saved at ${timeText}`;
    }

    function setSubmitStatus(text) {
      submitStatus.textContent = text;
    }

    function isModified() {
      return (editedText.value || '') !== originalChineseText;
    }

    function syncEditedHeight() {
      if (!highlightEnabled || !originalChineseHighlight) {
        return;
      }
      // Match the editable box to the rendered original Chinese box for this turn.
      const targetHeight = originalChineseHighlight.offsetHeight;
      if (targetHeight > 0) {
        editedText.style.height = `${targetHeight}px`;
      }
    }

    function renderHighlights() {
      if (!highlightEnabled || !originalChineseHighlight) {
        return;
      }
      const editedValue = editedText.value || '';
      const changed = computeChangedRanges(originalChineseText, editedValue);

      const originalClasses = new Array(originalChineseText.length).fill('');
      changed.originalRanges.forEach((range) => {
        for (let i = range.start; i < range.end; i += 1) {
          if (i >= 0 && i < originalClasses.length) originalClasses[i] = 'hl-yellow';
        }
      });

      originalChineseHighlight.innerHTML = renderOriginalWithInsertMarkers(
        originalChineseText,
        originalClasses,
        changed.insertionMarkers
      );
      syncEditedHeight();
    }

    function queueRenderHighlights() {
      if (!highlightEnabled) {
        return;
      }
      if (renderFrame !== null) {
        cancelAnimationFrame(renderFrame);
      }
      renderFrame = requestAnimationFrame(() => {
        renderFrame = null;
        renderHighlights();
      });
    }

    async function saveDraft(options) {
      if (isSubmitted) return;
      if (saveInFlight) {
        saveQueued = true;
        return;
      }
      saveInFlight = true;
      setSaving();
      try {
        const data = await postJson(`${doctorBasePath}/submission/${conversationId}/save-draft`, {
          translated_text_edited: editedText.value,
        });
        lastSavedValue = editedText.value;
        setSaved(data.last_saved_at);
      } catch (err) {
        autosaveStatus.textContent = `Save failed: ${err.message}`;
        if (options && options.throwOnError) {
          throw err;
        }
      } finally {
        saveInFlight = false;
        if (saveQueued && !isSubmitted && editedText.value !== lastSavedValue) {
          saveQueued = false;
          saveDraft(options);
        } else {
          saveQueued = false;
        }
      }
    }

    function lockSubmittedUi() {
      isSubmitted = true;
      item.dataset.status = 'submitted';
      editedText.setAttribute('disabled', 'disabled');
      if (discardBtn) {
        discardBtn.setAttribute('disabled', 'disabled');
      }
      if (autosaveTimer) {
        clearInterval(autosaveTimer);
        autosaveTimer = null;
      }
    }

    editedText.addEventListener('input', function () {
      if (isSubmitted) return;
      autosaveStatus.textContent = 'Unsaved changes';
      queueRenderHighlights();
      updateWorkspaceModifiedCount();
      saveDraft();
    });

    editedText.addEventListener('change', function () {
      if (isSubmitted) return;
      updateWorkspaceModifiedCount();
    });

    editedText.addEventListener('compositionend', function () {
      if (isSubmitted) return;
      updateWorkspaceModifiedCount();
    });

    editedText.addEventListener('blur', function () {
      if (isSubmitted) return;
      if (editedText.value === lastSavedValue) return;
      saveDraft();
    });

    autosaveTimer = setInterval(saveDraft, 10000);

    if (discardBtn) {
      discardBtn.addEventListener('click', async function () {
        if (isSubmitted) return;
        const ok = confirm('Reset this turn to the original Chinese text?');
        if (!ok) return;

        try {
          const data = await postJson(`${doctorBasePath}/submission/${conversationId}/discard`, {});
          editedText.value = data.translated_text_edited;
          lastSavedValue = editedText.value;
          setSubmitStatus(`Current status: ${data.status}`);
          setSaved(data.last_saved_at);
          queueRenderHighlights();
          updateWorkspaceModifiedCount();
        } catch (err) {
          alert(`Discard failed: ${err.message}`);
        }
      });
    }

    queueRenderHighlights();
    window.addEventListener('resize', syncEditedHeight);
    if (isSubmitted) {
      lockSubmittedUi();
    }

    async function submitCurrentTurn() {
      if (isSubmitted) {
        return { skipped: true };
      }

      await saveDraft({ throwOnError: true });
      const data = await postJson(`${doctorBasePath}/submission/${conversationId}/submit`, {
        consent_confirmed: true,
      });
      setSubmitStatus(`Current status: ${data.status} (submitted at ${data.submitted_at})`);
      autosaveStatus.textContent = 'Submission complete';
      lockSubmittedUi();
      return { skipped: false };
    }

    return {
      isSubmitted() {
        return isSubmitted;
      },
      isModified,
      getConversationId() {
        return conversationId;
      },
      flushDraftOnExit() {
        if (isSubmitted) {
          return;
        }
        if (editedText.value === lastSavedValue && !saveInFlight && !saveQueued) {
          return;
        }
        postJsonBeacon(`${doctorBasePath}/submission/${conversationId}/save-draft`, {
          translated_text_edited: editedText.value,
        });
      },
      submit() {
        return submitCurrentTurn();
      },
    };
  }

  const items = workspace.querySelectorAll('.conversation-item');
  const editors = Array.from(items, setupConversationEditor).filter(Boolean);

  function updateWorkspaceModifiedCount() {
    if (!workspaceModifiedCount) return;
    const modifiedCount = editors.filter((editor) => editor.isModified()).length;
    const totalCount = editors.length;
    workspaceModifiedCount.textContent = `Modified turns: ${modifiedCount} / ${totalCount}`;
  }

  function updateWorkspaceSubmitState() {
    if (!workspaceSubmitBtn || !workspaceSubmitStatus) return;
    const remainingCount = editors.filter((editor) => !editor.isSubmitted()).length;
    if (remainingCount === 0) {
      workspaceSubmitBtn.setAttribute('disabled', 'disabled');
      workspaceSubmitStatus.textContent = 'All turns on this page have been submitted.';
      return;
    }

    workspaceSubmitBtn.removeAttribute('disabled');
    workspaceSubmitStatus.textContent = `${remainingCount} turn${remainingCount === 1 ? '' : 's'} ready to submit on this page.`;
  }

  if (workspaceSubmitBtn) {
    workspaceSubmitBtn.addEventListener('click', async function () {
      if (document.activeElement && typeof document.activeElement.blur === 'function') {
        document.activeElement.blur();
      }
      updateWorkspaceModifiedCount();
      workspaceSubmitBtn.setAttribute('disabled', 'disabled');
      if (workspaceSubmitStatus) {
        workspaceSubmitStatus.textContent = 'Submitting all turns on this page...';
      }

      const failedConversationIds = [];
      let submittedCount = 0;

      for (const editor of editors) {
        try {
          const result = await editor.submit();
          if (!result.skipped) {
            submittedCount += 1;
          }
        } catch (err) {
          failedConversationIds.push(`Turn ${editor.getConversationId()}: ${err.message || 'Unknown error'}`);
        }
      }

      if (workspaceSubmitStatus) {
        if (failedConversationIds.length > 0) {
          workspaceSubmitStatus.textContent = `Submitted ${submittedCount} turn${submittedCount === 1 ? '' : 's'}, but ${failedConversationIds.length} failed.`;
        } else if (submittedCount === 0) {
          workspaceSubmitStatus.textContent = 'All turns on this page were already submitted.';
        } else {
          workspaceSubmitStatus.textContent = `Submitted ${submittedCount} turn${submittedCount === 1 ? '' : 's'} successfully. Creating workspace screenshot...`;
        }
      }

      if (failedConversationIds.length > 0) {
        alert(`Some turns could not be submitted:\n${failedConversationIds.join('\n')}`);
      } else if (submittedCount > 0) {
        try {
          await uploadWorkspaceScreenshot();
          if (workspaceSubmitStatus) {
            workspaceSubmitStatus.textContent = `Submitted ${submittedCount} turn${submittedCount === 1 ? '' : 's'} successfully. Workspace screenshot saved for admin download.`;
          }
        } catch (err) {
          if (workspaceSubmitStatus) {
            workspaceSubmitStatus.textContent = `Submitted ${submittedCount} turn${submittedCount === 1 ? '' : 's'} successfully, but screenshot capture failed.`;
          }
        }
      }

      updateWorkspaceSubmitState();
    });
  }

  updateWorkspaceModifiedCount();
  updateWorkspaceSubmitState();

  if (workspaceBackLink) {
    workspaceBackLink.addEventListener('click', function () {
      editors.forEach((editor) => editor.flushDraftOnExit());
    });
  }

  window.addEventListener('pagehide', function () {
    editors.forEach((editor) => editor.flushDraftOnExit());
  });
})();
