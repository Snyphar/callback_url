(() => {
  const fileInput = document.getElementById("template-file");
  const textArea = document.getElementById("template-text");
  const previewFrame = document.getElementById("preview-frame");
  const previewBtn = document.getElementById("preview-btn");
  const templateSelect = document.getElementById("template-select");
  const uploadFileInput = document.getElementById("template-upload-file");
  const savedTemplateSelect = document.getElementById("saved-template-select");
  const templatePreviewFrame = document.getElementById("template-preview-frame");
  const templateCode = document.getElementById("template-code");
  const templateMeta = document.getElementById("saved-template-meta");

  function updatePreview(html) {
    if (!previewFrame) return;
    previewFrame.srcdoc =
      html ||
      '<div style="padding:1rem;color:#666">No template to preview</div>';
  }

  function updateTemplatePage(html, meta) {
    if (templatePreviewFrame) {
      templatePreviewFrame.srcdoc =
        html || '<div style="padding:1rem;color:#666">No template selected</div>';
    }
    if (templateCode) templateCode.value = html || "";
    if (templateMeta && meta) templateMeta.textContent = meta;
  }

  if (fileInput) {
    fileInput.addEventListener("change", (ev) => {
      const f = ev.target.files && ev.target.files[0];
      if (!f) return;
      const reader = new FileReader();
      reader.onload = () => updatePreview(reader.result);
      reader.readAsText(f);
    });
  }

  if (textArea) {
    let tmr = null;
    textArea.addEventListener("input", () => {
      clearTimeout(tmr);
      tmr = setTimeout(() => updatePreview(textArea.value), 300);
    });
  }

  if (previewBtn) {
    previewBtn.addEventListener("click", () => {
      if (fileInput && fileInput.files && fileInput.files[0]) {
        const reader = new FileReader();
        reader.onload = () => updatePreview(reader.result);
        reader.readAsText(fileInput.files[0]);
      } else if (textArea) {
        updatePreview(textArea.value);
      }
    });
  }

  if (templateSelect) {
    templateSelect.addEventListener("change", (ev) => {
      const id = ev.target.value;
      if (id && window.TEMPLATES && window.TEMPLATES[id]) {
        const html = window.TEMPLATES[id];
        if (textArea) textArea.value = html;
        updatePreview(html);
      } else {
        // clear only if no file selected
        if (!fileInput || !fileInput.files.length) {
          if (textArea) textArea.value = "";
          updatePreview("");
        }
      }
    });
  }

  if (uploadFileInput) {
    uploadFileInput.addEventListener("change", (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) {
        updateTemplatePage("", "Select a saved template to view its code and preview.");
        return;
      }
      const reader = new FileReader();
      reader.onload = () => updateTemplatePage(String(reader.result || ""), `Unsaved preview: ${file.name}`);
      reader.readAsText(file);
    });
  }

  if (savedTemplateSelect) {
    savedTemplateSelect.addEventListener("change", (event) => {
      const template = window.SAVED_TEMPLATES && window.SAVED_TEMPLATES[event.target.value];
      if (!template) {
        updateTemplatePage("", "Select a saved template to view its code and preview.");
        return;
      }
      updateTemplatePage(template.html, `${template.name} - ${template.meta}`);
    });
  }

  // initial empty preview
  updatePreview("");
})();
