/* ============================================
   Theme Switcher — 三选一主题切换
   支持 volc / nerv / golden 三套主题
   - localStorage 持久化
   - 自动绑定 .theme-btn[data-theme] 按钮
   - 暴露全局函数 window.ThemeSwitcher
   ============================================ */
(function (global) {
  'use strict';

  // 合法主题列表
  var VALID_THEMES = ['volc', 'nerv', 'golden'];

  // 旧主题到新主题的映射（兼容历史 localStorage 记录）
  var LEGACY_THEME_MAP = {
    'light': 'volc',
    'dark': 'nerv',
    'warm': 'golden'
  };

  var STORAGE_KEY = 'theme';
  var DEFAULT_THEME = 'volc';

  /**
   * 获取当前主题
   * @returns {string} 当前主题名（volc / nerv / golden）
   */
  function getCurrentTheme() {
    var attr = document.documentElement.getAttribute('data-theme');
    if (attr && VALID_THEMES.indexOf(attr) !== -1) {
      return attr;
    }
    return DEFAULT_THEME;
  }

  /**
   * 规整主题值：合法直接返回；旧主题映射成新主题；其他回退默认
   * @param {string} theme
   * @returns {string}
   */
  function normalizeTheme(theme) {
    if (VALID_THEMES.indexOf(theme) !== -1) {
      return theme;
    }
    if (LEGACY_THEME_MAP[theme]) {
      return LEGACY_THEME_MAP[theme];
    }
    return DEFAULT_THEME;
  }

  /**
   * 更新所有主题按钮的选中态
   * @param {string} theme
   */
  function updateUI(theme) {
    var buttons = document.querySelectorAll('.theme-btn[data-theme]');
    buttons.forEach(function (btn) {
      var btnTheme = btn.getAttribute('data-theme');
      // 同时支持新主题按钮和映射后的旧主题按钮
      var normalized = normalizeTheme(btnTheme);
      if (normalized === theme) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });
  }

  /**
   * 切换主题
   * @param {string} theme 目标主题（volc / nerv / golden；旧值 light/dark/warm 会被映射）
   */
  function switchTheme(theme) {
    var normalized = normalizeTheme(theme);
    document.documentElement.setAttribute('data-theme', normalized);
    try {
      localStorage.setItem(STORAGE_KEY, normalized);
    } catch (e) {
      // localStorage 不可用时静默降级（隐私模式等）
    }
    updateUI(normalized);
    // 触发事件便于其他模块感知
    document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: normalized } }));
    return normalized;
  }

  /**
   * 初始化主题：从 localStorage 读取，无记录默认 volc
   */
  function initTheme() {
    var saved = null;
    try {
      saved = localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      // localStorage 不可用
    }
    var theme = normalizeTheme(saved);
    document.documentElement.setAttribute('data-theme', theme);
    updateUI(theme);

    // 绑定所有主题按钮点击事件
    bindThemeButtons();
  }

  /**
   * 绑定 .theme-btn[data-theme] 点击事件
   * 重复调用安全（已绑定的按钮会被跳过）
   */
  function bindThemeButtons() {
    var buttons = document.querySelectorAll('.theme-btn[data-theme]');
    buttons.forEach(function (btn) {
      if (btn.__themeBound) return;
      btn.__themeBound = true;
      btn.addEventListener('click', function () {
        var target = btn.getAttribute('data-theme');
        switchTheme(target);
      });
    });
  }

  // 暴露 API
  var ThemeSwitcher = {
    initTheme: initTheme,
    switchTheme: switchTheme,
    getCurrentTheme: getCurrentTheme,
    VALID_THEMES: VALID_THEMES
  };
  global.ThemeSwitcher = ThemeSwitcher;

  // 自动初始化：DOM 就绪后立即应用
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTheme);
  } else {
    initTheme();
  }
})(window);
