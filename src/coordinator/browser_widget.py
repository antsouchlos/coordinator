"""Small Jupyter frontend for editing names in the results overview."""

import anywidget
import traitlets


class ResultsOverview(anywidget.AnyWidget):
    """Render overview HTML and relay inline edits to the Python kernel."""

    html = traitlets.Unicode("").tag(sync=True)
    request = traitlets.Dict(default_value={}).tag(sync=True)
    response = traitlets.Dict(default_value={}).tag(sync=True)

    _esm = r"""
    export function render({model, el}) {
      el.classList.add('coordinator-root');
      let active = null;
      let serial = 0;
      const draw = () => {
        active = null;
        el.innerHTML = model.get('html');
      };
      const cancel = () => {
        if (!active) return;
        active.input.replaceWith(active.title);
        active.error.remove();
        active = null;
      };
      const submit = () => {
        if (!active || active.pending) return;
        const edit = active;
        if (edit.input.value === edit.title.dataset.editName) {
          cancel();
          return;
        }
        edit.pending = true;
        edit.input.disabled = true;
        const id = ++serial;
        edit.requestId = id;
        model.set('request', {id, action: 'rename', target: edit.target, name: edit.input.value});
        model.save_changes();
      };
      el.addEventListener('click', (event) => {
        if (event.target.matches('.coordinator-name-input')) {
          event.stopPropagation();
          return;
        }
        const title = event.target.closest('.coordinator-editable');
        if (title && el.contains(title)) {
          event.preventDefault();
          event.stopPropagation();
          if (active) cancel();
          const input = document.createElement('input');
          input.type = 'text';
          input.className = 'coordinator-name-input';
          input.value = title.dataset.editName;
          input.setAttribute('aria-label', `Rename ${title.dataset.kind}`);
          input.style.width = `${Math.max(100, title.getBoundingClientRect().width + 30)}px`;
          const error = document.createElement('span');
          error.className = 'coordinator-edit-error';
          title.replaceWith(input);
          input.after(error);
          active = {title, input, error, target: title.dataset.resultId, pending: false};
          input.addEventListener('keydown', (keyEvent) => {
            if (keyEvent.key === 'Escape') { keyEvent.preventDefault(); cancel(); }
            if (keyEvent.key === 'Enter') { keyEvent.preventDefault(); submit(); }
          });
          input.addEventListener('blur', submit);
          input.focus();
          input.select();
          return;
        }
        const button = event.target.closest('.coordinator-delete');
        if (!button || !el.contains(button)) return;
        event.preventDefault();
        event.stopPropagation();
        const name = button.dataset.displayName;
        const path = button.dataset.path;
        if (!window.confirm(`Permanently delete ${button.dataset.kind} “${name}” and everything under ${path}?`)) return;
        const id = ++serial;
        model.set('request', {id, action: 'delete', target: button.dataset.resultId});
        model.save_changes();
      });
      el.addEventListener('pointerdown', (event) => {
        if (event.target.closest('.coordinator-delete') && active) cancel();
      });
      el.addEventListener('keydown', (event) => {
        if (event.target.matches('.coordinator-editable') &&
            (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          event.target.click();
        }
      });
      model.on('change:response', () => {
        const response = model.get('response');
        if (response.ok) return;
        if (active && response.id === active.requestId) {
          active.pending = false;
          active.input.disabled = false;
          active.error.textContent = response.error;
          active.input.focus();
          return;
        }
        const button = el.querySelector(`[data-result-id="${response.target}"] .coordinator-delete`);
        if (button) button.title = response.error;
        window.alert(response.error);
      });
      model.on('change:html', draw);
      draw();
    }
    """

    _css = """
    .coordinator-root { display:block; width:100%; min-width:0; }
    .coordinator-editable { cursor:text; border-bottom:1px dotted transparent; }
    .coordinator-editable:hover { border-bottom-color:currentColor; }
    .coordinator-editable[data-edit-name=''] { color:#667; font-weight:normal; }
    .coordinator-name-input { font:inherit; font-weight:inherit; box-sizing:border-box; max-width:90%; }
    .coordinator-edit-error { color:#a22; font-size:12px; margin-left:6px; }
    .coordinator-delete { opacity:.35; border:0; background:transparent; color:inherit;
      cursor:pointer; padding:0 4px; display:inline-flex; align-items:center;
      vertical-align:middle; }
    .coordinator-delete svg { display:block; }
    .coordinator-delete:hover, .coordinator-delete:focus { opacity:1; color:#a22; }
    .coordinator-run-data,.coordinator-run-metadata { display:none; }
    .coordinator-run:has(.coordinator-view-data[open]) + .coordinator-run-data { display:table-row; }
    .coordinator-run:has(.coordinator-view-metadata[open]) + .coordinator-run-data +
      .coordinator-run-metadata { display:table-row; }
    .coordinator-attempt-body:has(> .coordinator-patch:not([open]))
      { grid-template-columns:minmax(0,1fr) max-content!important; }
    .coordinator-patch:not([open]) { width:max-content; justify-self:end; }
    .coordinator-patch:not([open]) .coordinator-patch-title { display:none; }
    .coordinator-patch:not([open]) .coordinator-patch-chevron { transform:rotate(-90deg); }
    .coordinator-patch summary::-webkit-details-marker { display:none; }
    .coordinator-panel > summary::-webkit-details-marker { display:none; }
    .coordinator-panel:not([open]) > summary .coordinator-panel-chevron
      { transform:rotate(-90deg); }
    """
