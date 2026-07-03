// Generic interactions: tabs, toggles, modals, tree nodes, panel resize
document.addEventListener('DOMContentLoaded', () => {

  // --- Tabs ---
  document.querySelectorAll('.tabs').forEach(tabBar => {
    const tabs = tabBar.querySelectorAll('.tab');
    const parent = tabBar.parentElement;
    const contents = parent.querySelectorAll('.tab-content');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        tabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        const target = tab.getAttribute('data-tab');
        contents.forEach(c => {
          c.classList.toggle('active', c.getAttribute('data-tab') === target);
        });
      });
    });
  });

  // --- Login Tabs ---
  document.querySelectorAll('.login-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const parent = tab.closest('.login-card');
      parent.querySelectorAll('.login-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const target = tab.getAttribute('data-form');
      parent.querySelectorAll('.login-form-content').forEach(f => {
        f.classList.toggle('active', f.getAttribute('data-form') === target);
      });
    });
  });

  // --- Toggle switches ---
  document.querySelectorAll('.toggle').forEach(toggle => {
    toggle.addEventListener('click', () => {
      toggle.classList.toggle('active');
    });
  });

  // --- Modal open/close ---
  document.querySelectorAll('[data-modal-open]').forEach(trigger => {
    trigger.addEventListener('click', () => {
      const modalId = trigger.getAttribute('data-modal-open');
      const overlay = document.getElementById(modalId);
      if (overlay) overlay.classList.add('open');
    });
  });

  document.querySelectorAll('[data-modal-close]').forEach(trigger => {
    trigger.addEventListener('click', () => {
      const overlay = trigger.closest('.modal-overlay');
      if (overlay) overlay.classList.remove('open');
    });
  });

  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.classList.remove('open');
    });
  });

  // --- Tree nodes ---
  document.querySelectorAll('.tree-node-toggle').forEach(toggle => {
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      toggle.classList.toggle('expanded');
      const children = toggle.closest('.tree-node').querySelector('.tree-children');
      if (children) children.style.display = children.style.display === 'none' ? 'block' : 'none';
    });
  });

  document.querySelectorAll('.tree-node-row').forEach(row => {
    row.addEventListener('click', () => {
      const view = row.closest('.tree-view');
      view.querySelectorAll('.tree-node-row').forEach(r => r.classList.remove('selected'));
      row.classList.add('selected');
      // Show detail
      const detailPanel = view.closest('.tree-content')?.querySelector('.tree-detail-panel');
      const detailEmpty = view.closest('.tree-content')?.querySelector('.tree-detail-empty');
      const detailContent = view.closest('.tree-content')?.querySelector('.tree-detail-content');
      if (detailPanel) {
        if (detailEmpty) detailEmpty.style.display = 'none';
        if (detailContent) detailContent.style.display = 'block';
      }
    });
  });

  // --- Chat panel divider drag ---
  const divider = document.querySelector('.chat-panel-divider');
  if (divider) {
    const panels = document.querySelector('.chat-panels');
    let isDragging = false;
    divider.addEventListener('mousedown', (e) => {
      isDragging = true;
      divider.classList.add('dragging');
      e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const rect = panels.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      const clamped = Math.max(25, Math.min(75, pct));
      panels.style.gridTemplateColumns = `${clamped}% ${100 - clamped}%`;
    });
    document.addEventListener('mouseup', () => {
      isDragging = false;
      divider.classList.remove('dragging');
    });
  }

  // --- Collapsible sections (task history) ---
  document.querySelectorAll('[data-collapse-toggle]').forEach(trigger => {
    trigger.addEventListener('click', () => {
      const target = document.getElementById(trigger.getAttribute('data-collapse-toggle'));
      if (target) {
        const isHidden = target.style.display === 'none';
        target.style.display = isHidden ? 'block' : 'none';
        trigger.querySelector('.collapse-icon')?.setAttribute(
          'transform', isHidden ? '' : 'rotate(180)'
        );
      }
    });
  });
});
