import { readdir, readFile } from 'node:fs/promises'
import { join, basename } from 'node:path'

const LIBRARY_COMPONENTS = [
  'AboutCard',
  'AdminUserTable',
  'InstanceModeControl',
  'AuthGate',
  'AboutLinkList',
  'AboutNote',
  'AboutFooterLine',
  'AboutPanel',
  'FamilyBadge',
  'TechChips',
  'SponsorCard',
  'AiActionsDropdown',
  'AiBadge',
  'AiButton',
  'AiMagicFill',
  'Badge',
  'Breadcrumbs',
  'Button',
  'Card',
  'CardHeader',
  'CardTitle',
  'CardDescription',
  'CardContent',
  'CardFooter',
  'useChatStream',
  'walkActivePath',
  'buildBranchTree',
  'ChatMessageView',
  'MarkdownSurface',
  'ChatMessage',
  'MessageVariantSwitcher',
  'ChatMessageEditor',
  'ChatReasoning',
  'ChatToolCard',
  'ChatTurnStatus',
  'ChatPending',
  'ChatWelcome',
  'ChatSearchField',
  'ChatSuggestionCard',
  'ToolCallCard',
  'TurnTraceStatus',
  'ThinkingDots',
  'ChatComposer',
  'ChatTranscript',
  'ChatBranchTree',
  'ChatSessionList',
  'ChatToolsCatalog',
  'ChatHistoryButton',
  'ChatTraceMeta',
  'ChatTraceTimeline',
  'ChatPanel',
  'ChatDrawer',
  'ChatLauncher',
  'MarkdownCodeBlock',
  'MermaidDiagram',
  'CheckIndicator',
  'ConnectionTestRow',
  'ChipInput',
  'ChipList',
  'Combobox',
  'RichTextEditor',
  'DictationButton',
  'DictationStrip',
  'TextDiffView',
  'MarkdownDiffView',
  'ComboboxMulti',
  'ConfirmationModal',
  'ContextMenu',
  'CopyButton',
  'DatePicker',
  'EmptyState',
  'ErrorBanner',
  'FileCard',
  'FileQueue',
  'FlowError',
  'FlowStatusCard',
  'FlowStep',
  'FlowTraceCard',
  'FlowTelemetryStrip',
  'FlowTrace',
  'ExpandableSearch',
  'FieldLabel',
  'FormModal',
  'InfoButton',
  'Input',
  'LoginForm',
  'RegisterForm',
  'CareerMark',
  'DesktopMark',
  'HealthMark',
  'NeuronectionMark',
  'NeuronectionWordmark',
  'StudyMark',
  'Marquee',
  'MarqueeBand',
  'MarqueeSurface',
  'Menu',
  'MenuContent',
  'MenuItem',
  'MenuCheckboxItem',
  'UserMenu',
  'ActionMenu',
  'Modal',
  'ModalContent',
  'ModelPicker',
  'ProviderSetupTiles',
  'ProviderSetupManualTile',
  'ProviderSetupForm',
  'SetupReview',
  'SetupFirstRunCard',
  'SwitchRow',
  'WebSearchProvidersPanel',
  'IntegrationCapabilityChips',
  'OriginChip',
  'StatusBadge',
  'TierBadge',
  'IntegrationCard',
  'IntegrationCatalogGrid',
  'IntegrationInstancesList',
  'IntegrationSourcesList',
  'AddIntegrationSourceDialog',
  'ConsentDialog',
  'IntegrationConfigForm',
  'ActionResultDialog',
  'DocsDialog',
  'SurfaceRenderer',
  'surfaceActionId',
  'surfaceProgressPercent',
  'ProviderLogo',
  'CapabilityChips',
  'CapabilityDescriptor',
  'ModelRegistry',
  'TaskAssignmentSection',
  'ModalHeader',
  'ModalTitle',
  'ModalDescription',
  'ModalFooter',
  'Portal',
  'Popover',
  'PopoverButton',
  'ProfileSwitcher',
  'ProviderForm',
  'RangeBar',
  'ScaleSlider',
  'scaleColorForValue',
  'SearchInput',
  'SegmentedTabs',
  'SelectionBar',
  'SettingsShell',
  'SidebarNav',
  'HoverCard',
  'HoverCardTrigger',
  'HoverCardContent',
  'Skeleton',
  'SkeletonText',
  'Spinner',
  'Stepper',
  'Table',
  'ThemeScope',
  'TimePicker',
  'TimeList',
  'Tooltip',
  'TooltipContent',
  'InfoTooltip',
  'UndoNotice',
  'UploadDropzone',
  'ViewToggle',
  'Wizard',
]

const usage = `usage: node scripts/audit-usage.mjs <app-src-dir> [--report]

Scans an app's source tree for local component files whose names shadow
library exports (ui/Button.tsx etc.). Exits 1 when drift is found unless
--report is passed (print only).`

const args = process.argv.slice(2)
const reportOnly = args.includes('--report')
const target = args.find((a) => !a.startsWith('--'))
if (!target) {
  console.error(usage)
  process.exit(2)
}

async function walk(dir, files = []) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue
    const full = join(dir, entry.name)
    if (entry.isDirectory()) await walk(full, files)
    else if (/\.(tsx|ts)$/.test(entry.name)) files.push(full)
  }
  return files
}

const files = await walk(target)
const findings = []
for (const file of files) {
  const name = basename(file).replace(/\.(tsx|ts)$/, '')
  const match = LIBRARY_COMPONENTS.find((c) => c.toLowerCase() === name.toLowerCase())
  if (match) {
    const source = await readFile(file, 'utf8')
    if (/from ['"]@neuronection\/assistant-ui/.test(source)) continue
    findings.push(file)
  }
}

if (findings.length === 0) {
  console.log(`audit-usage: clean (${files.length} files scanned in ${target})`)
  process.exit(0)
}

console.error(`audit-usage: local copies shadowing library components (same-commit delete rule):`)
for (const file of findings) console.error(`  ${file}`)
if (!reportOnly) process.exit(1)
