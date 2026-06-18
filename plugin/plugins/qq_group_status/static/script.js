const pluginId = 'qq_group_status';
const RUNS_URL = '/runs';

let currentStatus = null;

async function callPlugin(entry, args = {}) {
  const resp = await fetch(RUNS_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plugin_id: pluginId, entry_id: entry, args }),
  });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  const created = await resp.json();
  const runId = created.run_id || created.id;
  if (!runId) {
    throw new Error('未获取到 run_id');
  }

  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const poll = await fetch(`${RUNS_URL}/${runId}`);
    if (poll.ok) {
      const rec = await poll.json();
      if (rec.status === 'succeeded') {
        const exp = await fetch(`${RUNS_URL}/${runId}/export`);
        if (!exp.ok) {
          return {};
        }
        const { items = [] } = await exp.json();
        const item = items.find((candidate) => candidate.type === 'json' && candidate.json) || items[0];
        let raw = item?.json || {};
        while (raw && raw.data && typeof raw.data === 'object' && ('success' in raw.data || 'error' in raw.data)) {
          raw = raw.data;
        }
        return raw.value || raw.data || raw;
      }
      if (['failed', 'canceled', 'timeout'].includes(rec.status)) {
        throw new Error(rec.error?.message || rec.message || rec.status);
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error('调用超时');
}

function showToast(message) {
  const toast = document.getElementById('toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 2400);
}

function lines(value) {
  return String(value || '')
    .split(/\n|,|，|;|；/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function setLines(id, values) {
  document.getElementById(id).value = Array.isArray(values) ? values.join('\n') : '';
}

function peopleToText(people) {
  return (Array.isArray(people) ? people : [])
    .map((person) => {
      const keywords = Array.isArray(person.keywords) ? person.keywords.join(',') : '';
      return [person.qq || '', person.name || '', keywords].join('|').replace(/\|+$/g, '');
    })
    .filter(Boolean)
    .join('\n');
}

function stickerRulesToText(rules) {
  return (Array.isArray(rules) ? rules : [])
    .map((rule) => {
      const keywords = Array.isArray(rule.keywords) ? rule.keywords.join(',') : '';
      const reasons = Array.isArray(rule.reasons) ? rule.reasons.join(',') : '';
      const probability = rule.probability === undefined ? '1' : String(rule.probability);
      return [rule.label || rule.id || '', rule.file || '', keywords, reasons, probability].join('|').replace(/\|+$/g, '');
    })
    .filter(Boolean)
    .join('\n');
}

function renderStickerLibrary(stickers) {
  const root = document.getElementById('sticker-library');
  if (!root) {
    return;
  }
  root.replaceChildren();
  if (!Array.isArray(stickers) || !stickers.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = '暂无表情包';
    root.appendChild(empty);
    return;
  }
  stickers.forEach((sticker) => {
    const item = document.createElement('div');
    item.className = 'sticker-item';

    const name = document.createElement('strong');
    name.textContent = sticker.label || sticker.id || '未命名';

    const path = document.createElement('span');
    path.textContent = sticker.file || '';

    item.append(name, path);
    root.appendChild(item);
  });
}

function textToPeople(raw) {
  return String(raw || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [qq = '', name = '', keywordText = ''] = line.split('|').map((item) => item.trim());
      return {
        qq,
        name,
        keywords: lines(keywordText),
      };
    })
    .filter((person) => person.qq);
}

function textToStickerRules(raw) {
  return String(raw || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const [label = '', file = '', keywordText = '', reasonText = '', probabilityText = '1'] = line.split('|').map((item) => item.trim());
      return {
        id: label || `sticker_${index + 1}`,
        label,
        file,
        keywords: lines(keywordText),
        reasons: lines(reasonText),
        probability: Number.isFinite(Number(probabilityText)) ? Number(probabilityText) : 1,
      };
    })
    .filter((rule) => rule.file);
}

function numberValue(id, fallback) {
  const value = Number(document.getElementById(id).value);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function readFormConfig() {
  return {
    onebot_url: document.getElementById('onebot-url').value.trim(),
    token: document.getElementById('token').value,
    auto_start_monitor: document.getElementById('auto-start').checked,
    monitored_groups: lines(document.getElementById('monitored-groups').value),
    authorized_qq_numbers: lines(document.getElementById('authorized-qqs').value),
    responsible_people: textToPeople(document.getElementById('responsible-people').value),
    project_keywords: lines(document.getElementById('project-keywords').value),
    question_keywords: lines(document.getElementById('question-keywords').value),
    question_detection_enabled: document.getElementById('question-enabled').checked,
    archive_detection_enabled: document.getElementById('archive-enabled').checked,
    media_detection_enabled: false,
    mention_reply_enabled: document.getElementById('mention-reply-enabled').checked,
    daily_chat_reply_enabled: document.getElementById('daily-chat-enabled').checked,
    daily_chat_requires_mention: document.getElementById('daily-chat-requires-mention').checked,
    issue_forwarding_enabled: document.getElementById('issue-forwarding-enabled').checked,
    issue_forward_target_type: document.getElementById('issue-forward-target-type').value,
    issue_forward_target_id: document.getElementById('issue-forward-group').value.trim(),
    issue_forward_group_id: document.getElementById('issue-forward-group').value.trim(),
    mention_staff_on_question: document.getElementById('mention-staff-enabled').checked,
    popup_notifications: document.getElementById('popup-enabled').checked,
    use_llm_reply: document.getElementById('llm-reply-enabled').checked,
    sticker_enabled: document.getElementById('sticker-enabled').checked,
    sticker_rules: textToStickerRules(document.getElementById('sticker-rules').value),
    notify_cooldown_seconds: numberValue('notify-cooldown', 90),
    reply_cooldown_seconds: numberValue('reply-cooldown', 45),
    staff_mention_cooldown_seconds: numberValue('staff-cooldown', 180),
    sticker_cooldown_seconds: numberValue('sticker-cooldown', 60),
    catgirl_reply_template: document.getElementById('catgirl-template').value.trim(),
    daily_chat_reply_template: document.getElementById('daily-chat-template').value.trim(),
    staff_ping_template: document.getElementById('staff-template').value.trim(),
  };
}

function applyConfig(config) {
  document.getElementById('onebot-url').value = config.onebot_url || '';
  document.getElementById('token').value = config.token || '';
  document.getElementById('auto-start').checked = Boolean(config.auto_start_monitor);
  setLines('monitored-groups', config.monitored_groups);
  setLines('authorized-qqs', config.authorized_qq_numbers);
  document.getElementById('responsible-people').value = peopleToText(config.responsible_people);
  setLines('project-keywords', config.project_keywords);
  setLines('question-keywords', config.question_keywords);
  document.getElementById('question-enabled').checked = Boolean(config.question_detection_enabled);
  document.getElementById('archive-enabled').checked = Boolean(config.archive_detection_enabled);
  document.getElementById('mention-reply-enabled').checked = Boolean(config.mention_reply_enabled);
  document.getElementById('daily-chat-enabled').checked = Boolean(config.daily_chat_reply_enabled);
  document.getElementById('daily-chat-requires-mention').checked = Boolean(config.daily_chat_requires_mention);
  document.getElementById('issue-forwarding-enabled').checked = Boolean(config.issue_forwarding_enabled);
  document.getElementById('issue-forward-target-type').value = config.issue_forward_target_type === 'user' ? 'user' : 'group';
  document.getElementById('issue-forward-group').value = config.issue_forward_target_id || config.issue_forward_group_id || '';
  document.getElementById('mention-staff-enabled').checked = Boolean(config.mention_staff_on_question);
  document.getElementById('popup-enabled').checked = Boolean(config.popup_notifications);
  document.getElementById('llm-reply-enabled').checked = Boolean(config.use_llm_reply);
  document.getElementById('sticker-enabled').checked = Boolean(config.sticker_enabled);
  document.getElementById('notify-cooldown').value = String(config.notify_cooldown_seconds ?? 90);
  document.getElementById('reply-cooldown').value = String(config.reply_cooldown_seconds ?? 45);
  document.getElementById('staff-cooldown').value = String(config.staff_mention_cooldown_seconds ?? 180);
  document.getElementById('sticker-cooldown').value = String(config.sticker_cooldown_seconds ?? 60);
  document.getElementById('catgirl-template').value = config.catgirl_reply_template || '';
  document.getElementById('daily-chat-template').value = config.daily_chat_reply_template || '';
  document.getElementById('staff-template').value = config.staff_ping_template || '';
  document.getElementById('sticker-rules').value = stickerRulesToText(config.sticker_rules);
  renderStickerLibrary(config.sticker_library);
  setForwardingModeControls();
}

function setMetric(id, value) {
  document.getElementById(id).textContent = String(value);
}

function setForwardingModeControls() {
  const enabled = Boolean(document.getElementById('issue-forwarding-enabled')?.checked);
  document.querySelectorAll('[data-forward-disabled="true"]').forEach((element) => {
    element.disabled = enabled;
    const label = element.closest('label');
    if (label) {
      label.classList.toggle('disabled-field', enabled);
    }
  });
}

function renderSetupChecks(checks) {
  const root = document.getElementById('setup-checks');
  if (!root) {
    return;
  }
  root.replaceChildren();
  const napcat = checks?.napcat || {};
  const forwardingEnabled = Boolean(currentStatus?.config?.issue_forwarding_enabled);
  const forwardTargetType = currentStatus?.config?.issue_forward_target_type === 'user' ? '好友' : '群聊';
  const items = [
    {
      label: 'NapCat.Shell 本地目录',
      ok: Boolean(napcat.detected),
      detail: napcat.detected ? `已检测到：${napcat.path || ''}` : `未检测到，可下载 ${napcat.recommended_package || 'NapCat.Shell.zip'}`,
    },
    {
      label: 'OneBot 地址',
      ok: Boolean(checks?.onebot_url_configured),
      detail: checks?.onebot_url_configured ? '地址格式有效' : '请填写 ws:// 或 wss:// 地址',
    },
    {
      label: 'OneBot 连接',
      ok: Boolean(checks?.onebot_connected),
      detail: checks?.onebot_connected ? '已连接' : '启动 NapCat 后点击启动监听',
    },
    {
      label: '监控范围',
      ok: true,
      detail: checks?.monitor_scope === 'configured_groups' ? '已指定群号' : '当前监听所有群',
    },
    {
      label: '授权 QQ',
      ok: forwardingEnabled || Boolean(checks?.authorized_qq_configured),
      detail: forwardingEnabled ? '转移模式不需要' : (checks?.authorized_qq_configured ? '已配置' : '请至少填写一个被 @ 时要响应的 QQ'),
    },
    {
      label: '相关负责人',
      ok: forwardingEnabled || Boolean(checks?.responsible_people_configured),
      detail: forwardingEnabled ? '转移模式不需要' : (checks?.responsible_people_configured ? '触发时随机 @ 一位' : '建议填写需要被 @ 协助的人'),
    },
    {
      label: '压缩包提醒',
      ok: Boolean(currentStatus?.config?.archive_detection_enabled),
      detail: currentStatus?.config?.archive_detection_enabled ? 'zip / rar / 7z 等文件会触发' : '已关闭压缩包提醒',
    },
    {
      label: '日常聊天',
      ok: Boolean(currentStatus?.config?.daily_chat_reply_enabled),
      detail: currentStatus?.config?.daily_chat_reply_enabled ? '授权 QQ 被 @ 时会回到群里' : '已关闭日常聊天回复',
    },
    {
      label: '问题转移',
      ok: Boolean(checks?.issue_forwarding_configured),
      detail: checks?.issue_forwarding_configured ? `转发到${forwardTargetType} ${currentStatus?.config?.issue_forward_target_id || currentStatus?.config?.issue_forward_group_id || ''}` : '未启用',
    },
    {
      label: '表情包库',
      ok: Boolean(checks?.sticker_rules_configured),
      detail: checks?.sticker_rules_configured ? '已配置，猫娘会按名称选择' : '可选：导入后猫娘会按名称选择',
    },
  ];
  items.forEach((item) => {
    const card = document.createElement('div');
    card.className = `check-card ${item.ok ? 'ok' : 'pending'}`;

    const title = document.createElement('strong');
    title.textContent = item.label;

    const detail = document.createElement('span');
    detail.textContent = item.detail;

    card.append(title, detail);
    root.appendChild(card);
  });
}

function renderEvents(events) {
  const root = document.getElementById('events-list');
  root.replaceChildren();
  if (!Array.isArray(events) || !events.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = '暂无事件';
    root.appendChild(empty);
    return;
  }
  events.slice(0, 20).forEach((event) => {
    const decision = event.decision || {};
    const item = document.createElement('div');
    item.className = 'event-item';

    const meta = document.createElement('div');
    meta.className = 'event-meta';
    meta.textContent = `群 ${event.group_id || '-'} · ${event.sender_name || event.sender_id || '-'} · ${new Date((event.timestamp || 0) * 1000).toLocaleString()}`;

    const reasons = document.createElement('div');
    reasons.className = 'event-reasons';
    reasons.textContent = Array.isArray(decision.reasons) ? decision.reasons.join(', ') : '-';

    const text = document.createElement('div');
    text.className = 'event-text';
    text.textContent = decision.text || '（无文本内容）';

    item.append(meta, reasons, text);
    root.appendChild(item);
  });
}

function applyStatus(status) {
  currentStatus = status || {};
  const config = currentStatus.config || {};
  applyConfig(config);
  const running = Boolean(currentStatus.monitor_running);
  const connected = Boolean(currentStatus.onebot_connected);
  document.getElementById('status-line').textContent = running
    ? (connected ? '监听中 · OneBot 已连接' : '监听中 · OneBot 重连中')
    : '未监听';
  setMetric('metric-running', running ? '运行中' : '已停止');
  setMetric('metric-onebot', connected ? '已连接' : '未连接');
  setMetric('metric-groups', Array.isArray(config.monitored_groups) && config.monitored_groups.length ? config.monitored_groups.length : '全部');
  setMetric('metric-authorized', Array.isArray(config.authorized_qq_numbers) ? config.authorized_qq_numbers.length : 0);
  renderSetupChecks(currentStatus.setup_checks || {});
  renderEvents(currentStatus.recent_events || []);
}

async function reloadStatus() {
  const status = await callPlugin('get_status');
  applyStatus(status);
  return status;
}

async function saveConfig(event) {
  event?.preventDefault();
  const saved = await callPlugin('save_config', { config: readFormConfig() });
  applyStatus(saved);
  showToast(saved.reconnect_required ? '已保存，重启监听后生效' : '已保存');
}

async function startMonitor() {
  const status = await callPlugin('start_monitor');
  applyStatus(status);
  showToast('监听已启动');
}

async function stopMonitor() {
  const status = await callPlugin('stop_monitor');
  applyStatus(status);
  showToast('监听已停止');
}

async function testEvaluate() {
  const text = document.getElementById('test-text').value;
  const atTargets = lines(document.getElementById('test-at').value);
  const fileNames = lines(document.getElementById('test-files').value);
  const result = await callPlugin('test_evaluate_message', {
    text,
    at_targets: atTargets,
    file_names: fileNames,
  });
  document.getElementById('test-output').textContent = JSON.stringify(result, null, 2);
}

function readFileAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('读取文件失败'));
    reader.readAsDataURL(file);
  });
}

async function importStickers() {
  const input = document.getElementById('sticker-files');
  const files = Array.from(input.files || []);
  if (!files.length) {
    showToast('请选择表情包文件');
    return;
  }
  const payload = [];
  for (const file of files) {
    payload.push({
      name: file.name.replace(/\.[^.]+$/, ''),
      filename: file.name,
      data_url: await readFileAsDataURL(file),
    });
  }
  const status = await callPlugin('import_stickers', { files: payload });
  applyStatus(status);
  input.value = '';
  showToast(`已导入 ${payload.length} 个表情包`);
}

function bindEvents() {
  document.getElementById('settings-form').addEventListener('submit', (event) => {
    saveConfig(event).catch((error) => showToast(error.message || '保存失败'));
  });
  document.getElementById('refresh-btn').addEventListener('click', () => {
    reloadStatus().catch((error) => showToast(error.message || '刷新失败'));
  });
  document.getElementById('start-btn').addEventListener('click', () => {
    startMonitor().catch((error) => showToast(error.message || '启动失败'));
  });
  document.getElementById('stop-btn').addEventListener('click', () => {
    stopMonitor().catch((error) => showToast(error.message || '停止失败'));
  });
  document.getElementById('test-btn').addEventListener('click', () => {
    testEvaluate().catch((error) => showToast(error.message || '测试失败'));
  });
  document.getElementById('import-stickers-btn').addEventListener('click', () => {
    importStickers().catch((error) => showToast(error.message || '导入失败'));
  });
  document.getElementById('issue-forwarding-enabled').addEventListener('change', () => {
    setForwardingModeControls();
  });
}

bindEvents();
reloadStatus().catch((error) => showToast(error.message || '加载失败'));
