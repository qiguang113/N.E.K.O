import { useEffect, useState } from "@neko/plugin-ui"
import {
  Page,
  Card,
  Stack,
  Grid,
  Text,
  Heading,
  Divider,
  StatusBadge,
  KeyValue,
  Switch,
  Input,
  Select,
  ActionButton,
  Alert,
  Tip,
  EmptyState,
  InlineError,
  Section,
  List,
} from "@neko/plugin-ui"
import type { HostedAction, PluginSurfaceProps } from "@neko/plugin-ui"

// ── Types ────────────────────────────────────────────────────────────────────

type ReaderState = {
  running: boolean
  process_pid: number
  engine: string
  hook_code: string
  lines_read: number
  last_line_at: number
  error: string
} | null

type ConfigState = {
  memory_mix_enabled: boolean
  max_context_lines: number
  reply_cooldown_seconds: number
  min_lines_before_reply: number
  greet_on_scene_change: boolean
  scene_change_cooldown_seconds: number
  push_priority: number
  include_line_quote: boolean
  max_reply_chars: number
  poll_interval: number
  idle_timeout: number
}

type ProcessInfo = {
  name: string
  pid: number
}

type DashboardState = {
  running: boolean
  reader: ReaderState
  config: ConfigState
  pending_lines_count: number
  recent_pending_lines: string[]
  last_push_time: number
  last_push_content: string
  last_error: string
  candidate_processes: ProcessInfo[]
}

// ── Component ────────────────────────────────────────────────────────────────

export default function Panel(props: PluginSurfaceProps<DashboardState>) {
  const { t, state, actions, api, plugin } = props

  // ── Locate actions ──
  const toggleMemMix = actions.find((a) => a.id === "toggle_memory_mix") as HostedAction | undefined
  const scanProcs = actions.find((a) => a.id === "scan_processes") as HostedAction | undefined
  const startReader = actions.find((a) => a.id === "start_reader") as HostedAction | undefined
  const stopReader = actions.find((a) => a.id === "stop_reader") as HostedAction | undefined

  // ── Local input state for reader start ──
  const [targetPid, setTargetPid] = useState<number>(0)
  const [targetEngine, setTargetEngine] = useState<string>("auto")
  const [targetHookCode, setTargetHookCode] = useState<string>("")

  // ── Local process list (augmented from api scan) ──
  const [scannedProcesses, setScannedProcesses] = useState<ProcessInfo[]>([])
  const [scanning, setScanning] = useState(false)

  // Sync from context
  useEffect(() => {
    if (state?.candidate_processes?.length) {
      setScannedProcesses(state.candidate_processes)
    }
  }, [state?.candidate_processes])

  const doScan = async () => {
    if (!scanProcs) return
    setScanning(true)
    try {
      const r = await api.call("scan_processes")
      if (r?.value?.processes) {
        setScannedProcesses(r.value.processes)
      }
    } catch (_) {
    } finally {
      setScanning(false)
    }
  }

  const doStartReader = async (pid: number) => {
    if (!startReader) return
    try {
      await api.call("start_reader", {
        pid,
        hook_code: targetHookCode,
        engine: targetEngine || "auto",
      })
    } catch (_) {}
  }

  const doStopReader = async () => {
    if (!stopReader) return
    try {
      await api.call("stop_reader")
    } catch (_) {}
  }

  const doToggleMemMix = async () => {
    if (!toggleMemMix) return
    try {
      await api.call("toggle_memory_mix", {
        enabled: !state?.config?.memory_mix_enabled,
      })
    } catch (_) {}
  }

  const doRefresh = async () => {
    try {
      await api.refresh()
    } catch (_) {}
  }

  // ── Derived data ──
  const readerRunning = state?.reader?.running ?? false
  const memoryMixOn = state?.config?.memory_mix_enabled ?? false
  const lastPushAgo = state?.last_push_time
    ? Math.round((Date.now() - state.last_push_time * 1000) / 1000)
    : null

  // ── Render ──
  return (
    <Page title={plugin.name} subtitle={t("panel.subtitle")}>
      {/* ── Status Overview ── */}
      <Card title={t("panel.status")}>
        <Grid cols={3}>
          <StatusBadge
            label={readerRunning ? t("status.reading") : t("status.idle")}
            tone={readerRunning ? "success" : "neutral"}
          />
          <StatusBadge
            label={
              memoryMixOn ? t("status.memory_mix.on") : t("status.memory_mix.off")
            }
            tone={memoryMixOn ? "info" : "neutral"}
          />
          <StatusBadge
            label={t("status.lines_pending", { count: state?.pending_lines_count ?? 0 })}
            tone={(state?.pending_lines_count ?? 0) > 0 ? "warning" : "neutral"}
          />
        </Grid>

        {state?.last_error ? (
          <InlineError error={state.last_error} />
        ) : null}
      </Card>

      {/* ── Memory Mix Toggle ── */}
      <Card title={t("panel.memory_mix")}>
        <Stack>
          <Switch
            checked={memoryMixOn}
            onChange={doToggleMemMix}
            label={memoryMixOn ? t("panel.memory_mix_on_label") : t("panel.memory_mix_off_label")}
          />
          <Text tone="secondary">
            {memoryMixOn
              ? t("panel.memory_mix_on_desc")
              : t("panel.memory_mix_off_desc")}
          </Text>
        </Stack>
      </Card>

      {/* ── Process Detection ── */}
      <Card title={t("panel.process")}>
        <Stack>
          <Grid cols={2}>
            {scanProcs ? (
              <ActionButton action={scanProcs} onClick={doScan} loading={scanning}>
                {t("actions.scan_processes.label")}
              </ActionButton>
            ) : null}
            {readerRunning ? (
              <ActionButton action={stopReader!} onClick={doStopReader} tone="danger">
                {t("actions.stop_reader.label")}
              </ActionButton>
            ) : null}
          </Grid>

          {readerRunning ? (
            <Stack>
              <Alert tone="success" title={t("panel.reader_active")}>
                {t("panel.reader_active_desc", {
                  pid: String(state?.reader?.process_pid ?? 0),
                  engine: state?.reader?.engine || "auto",
                  lines: String(state?.reader?.lines_read ?? 0),
                })}
              </Alert>
              <KeyValue
                entries={[
                  { key: "PID", value: String(state?.reader?.process_pid ?? "-") },
                  { key: t("fields.engine"), value: state?.reader?.engine || "auto" },
                  { key: t("fields.lines_read"), value: String(state?.reader?.lines_read ?? 0) },
                  { key: t("fields.hook_code"), value: state?.reader?.hook_code || "-" },
                ]}
              />
            </Stack>
          ) : (
            <Tip>{t("panel.process_help")}</Tip>
          )}

          {scannedProcesses.length > 0 ? (
            <Stack>
              <Heading level={4}>{t("panel.found_processes")}</Heading>
              <List
                items={scannedProcesses}
                renderItem={(proc: ProcessInfo) => (
                  <Grid cols={4}>
                    <Text>{proc.name}</Text>
                    <Text>PID: {proc.pid}</Text>
                    <ActionButton
                      action={startReader!}
                      onClick={() => doStartReader(proc.pid)}
                      tone="success"
                    >
                      {t("actions.start_for_pid", { pid: String(proc.pid) })}
                    </ActionButton>
                  </Grid>
                )}
              />
            </Stack>
          ) : null}

          {/* Manual PID input */}
          {!readerRunning ? (
            <Grid cols={3}>
              <Input
                type="number"
                value={targetPid > 0 ? String(targetPid) : ""}
                onChange={(v) => setTargetPid(Number(v) || 0)}
                label={t("fields.target_pid")}
                placeholder="12345"
              />
              <Select
                value={targetEngine}
                onChange={setTargetEngine}
                label={t("fields.engine")}
                options={[
                  { value: "auto", label: t("engine.auto") },
                  { value: "unity", label: "Unity" },
                  { value: "kirikiri", label: "Kirikiri" },
                  { value: "renpy", label: "Ren'Py" },
                ]}
              />
              <Input
                value={targetHookCode}
                onChange={setTargetHookCode}
                label={t("fields.hook_code")}
                placeholder="/HQ14+3C@GameAssembly.dll#0x33A440"
              />
            </Grid>
          ) : null}

          {!readerRunning && startReader ? (
            <ActionButton
              action={startReader}
              onClick={() => doStartReader(targetPid)}
              tone="success"
            >
              {t("actions.start_reader.label")}
            </ActionButton>
          ) : null}
        </Stack>
      </Card>

      {/* ── Recent Game Lines ── */}
      <Card title={t("panel.recent_lines")}>
        {state?.recent_pending_lines?.length ? (
          <Stack>
            {state.recent_pending_lines.slice(-10).map((line, i) => (
              <Text key={i} tone="secondary">
                {String(i + 1)}. {line}
              </Text>
            ))}
          </Stack>
        ) : (
          <EmptyState title={t("panel.no_lines")} description={t("panel.no_lines_desc")} />
        )}
      </Card>

      {/* ── Last Push ── */}
      {state?.last_push_content ? (
        <Card title={t("panel.last_push")}>
          <Stack>
            {lastPushAgo !== null ? (
              <Text tone="secondary">{t("panel.last_push_ago", { sec: String(lastPushAgo) })}</Text>
            ) : null}
            <Text>{state.last_push_content}</Text>
          </Stack>
        </Card>
      ) : null}

      {/* ── Speed Dial ── */}
      <Card title={t("panel.quick_config")}>
        <Section title={t("panel.reply_settings")}>
          <Grid cols={3}>
            <KeyValue
              entries={[
                { key: t("fields.cooldown"), value: t("fields.cooldown_value", { sec: String(state?.config?.reply_cooldown_seconds ?? 8) }) },
                { key: t("fields.min_lines"), value: String(state?.config?.min_lines_before_reply ?? 4) },
                { key: t("fields.max_context"), value: String(state?.config?.max_context_lines ?? 20) },
                { key: t("fields.max_reply_chars"), value: String(state?.config?.max_reply_chars ?? 300) },
                { key: t("fields.push_priority"), value: String(state?.config?.push_priority ?? 6) },
                { key: t("fields.poll_interval"), value: t("fields.poll_interval_value", { sec: String(state?.config?.poll_interval ?? 1) }) },
              ]}
            />
          </Grid>
        </Section>

        <Tip>{t("panel.config_help")}</Tip>
      </Card>
    </Page>
  )
}
