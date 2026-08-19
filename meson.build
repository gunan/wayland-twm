project(
  'wtwm',
  'c',
  version: '0.1.0',
  license: 'MIT',
  meson_version: '>=0.60.0',
  default_options: ['c_std=c11', 'warning_level=3'],
)

cc = meson.get_compiler('c')
inc = include_directories('include')

config_args = [
  '-DWTWM_SYSTEM_CONFIG="' + get_option('prefix') / get_option('datadir') / 'wtwm/system.twmrc' + '"',
]

font_lib = static_library(
  'wtwm-font-lib',
  'src/font.c',
  include_directories: inc,
)
font_dep = declare_dependency(
  link_with: font_lib,
  include_directories: inc,
)

font_test = executable(
  'font-test',
  'tests/font_test.c',
  dependencies: font_dep,
)
test('X core bitmap font metrics', font_test)

color_lib = static_library(
  'wtwm-color-lib',
  'src/color.c',
  include_directories: inc,
)
color_dep = declare_dependency(
  link_with: color_lib,
  include_directories: inc,
)

color_test = executable(
  'color-test',
  'tests/color_test.c',
  dependencies: color_dep,
)
test('X11 color conversion', color_test)

xbm_lib = static_library(
  'wtwm-xbm-lib',
  'src/xbm.c',
  include_directories: inc,
)
xbm_dep = declare_dependency(
  link_with: xbm_lib,
  include_directories: inc,
)

xbm_test = executable(
  'xbm-test',
  'tests/xbm_test.c',
  dependencies: xbm_dep,
)
test(
  'XBM loader',
  xbm_test,
  env: ['WTWM_SOURCE_ROOT=' + meson.project_source_root()],
)

placement_lib = static_library(
  'wtwm-placement-lib',
  'src/placement.c',
  include_directories: inc,
)
placement_dep = declare_dependency(
  link_with: placement_lib,
  include_directories: inc,
)

placement_test = executable(
  'placement-test',
  'tests/placement_test.c',
  dependencies: placement_dep,
)
test('twm placement policy', placement_test)
test(
  'placement runtime contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_placement_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)

config_lib = static_library(
  'wtwm-config-lib',
  'src/config.c',
  include_directories: inc,
  c_args: config_args,
  dependencies: placement_dep,
)
config_dep = declare_dependency(
  link_with: config_lib,
  include_directories: inc,
  dependencies: placement_dep,
)

icon_layout_lib = static_library(
  'wtwm-icon-layout-lib',
  'src/icon_layout.c',
  include_directories: inc,
  dependencies: config_dep,
)
icon_layout_dep = declare_dependency(
  link_with: icon_layout_lib,
  include_directories: inc,
  dependencies: config_dep,
)

icon_layout_test = executable(
  'icon-layout-test',
  'tests/icon_layout_test.c',
  dependencies: icon_layout_dep,
)
test('twm icon-region allocator', icon_layout_test)

icon_manager_lib = static_library(
  'wtwm-icon-manager-lib',
  'src/icon_manager.c',
  include_directories: inc,
)
icon_manager_dep = declare_dependency(
  link_with: icon_manager_lib,
  include_directories: inc,
)

icon_manager_test = executable(
  'icon-manager-test',
  'tests/icon_manager_test.c',
  dependencies: icon_manager_dep,
)
test('twm icon-manager model', icon_manager_test)
test(
  'Milestone 7 icon runtime contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_m7_icon_runtime.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'Milestone 7 live icon differential contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/run_m7_icon_differential.py'),
    '--self-test',
  ],
)
test(
  'Milestone 7 deterministic lifecycle churn contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/run_m7_lifecycle_churn.py'),
    '--self-test',
  ],
)
test(
  'reference twm icon behavior contract',
  find_program('python3'),
  args: [files('tests/reference/validate_reference_icon_contract.py')],
)

geometry_lib = static_library(
  'wtwm-geometry-lib',
  'src/geometry.c',
  include_directories: inc,
)
geometry_dep = declare_dependency(
  link_with: geometry_lib,
  include_directories: inc,
)

visual_lib = static_library(
  'wtwm-visual-lib',
  'src/visual.c',
  include_directories: inc,
)
visual_dep = declare_dependency(
  link_with: visual_lib,
  include_directories: inc,
)

visual_test = executable(
  'visual-test',
  'tests/visual_test.c',
  dependencies: visual_dep,
)
test('twm visual layout', visual_test)
test(
  'Milestone 5 visual contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_m5_visual.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)

interaction_lib = static_library(
  'wtwm-interaction-lib',
  'src/interaction.c',
  include_directories: inc,
)
interaction_dep = declare_dependency(
  link_with: interaction_lib,
  include_directories: inc,
)

interaction_test = executable(
  'interaction-test',
  'tests/interaction_test.c',
  dependencies: interaction_dep,
)
test('twm move and resize interaction model', interaction_test)

actions_lib = static_library(
  'wtwm-actions-lib',
  'src/actions.c',
  include_directories: inc,
)
actions_dep = declare_dependency(
  link_with: actions_lib,
  include_directories: inc,
)

actions_test = executable(
  'actions-test',
  'tests/actions_test.c',
  dependencies: actions_dep,
)
test('twm built-in action model', actions_test)

output_order_lib = static_library(
  'wtwm-output-order-lib',
  'src/output_order.c',
  include_directories: inc,
)
output_order_dep = declare_dependency(
  link_with: output_order_lib,
  include_directories: inc,
)

output_order_test = executable(
  'output-order-test',
  'tests/output_order_test.c',
  dependencies: output_order_dep,
)
test('Wayland output screen ordering', output_order_test)

output_topology_lib = static_library(
  'wtwm-output-topology-lib',
  'src/output_topology.c',
  include_directories: inc,
)
output_topology_dep = declare_dependency(
  link_with: output_topology_lib,
  include_directories: inc,
)

output_topology_test = executable(
  'output-topology-test',
  'tests/output_topology_test.c',
  dependencies: output_topology_dep,
)
test('Wayland output topology transaction model', output_topology_test)

output_restore_lib = static_library(
  'wtwm-output-restore-lib',
  'src/output_restore.c',
  include_directories: inc,
  dependencies: placement_dep,
)
output_restore_dep = declare_dependency(
  link_with: output_restore_lib,
  include_directories: inc,
  dependencies: placement_dep,
)

output_restore_test = executable(
  'output-restore-test',
  'tests/output_restore_test.c',
  dependencies: output_restore_dep,
)
test('Wayland disappeared-output restoration model', output_restore_test)

input_hotplug_lib = static_library(
  'wtwm-input-hotplug-lib',
  'src/input_hotplug.c',
  include_directories: inc,
)
input_hotplug_dep = declare_dependency(
  link_with: input_hotplug_lib,
  include_directories: inc,
)

input_hotplug_test = executable(
  'input-hotplug-test',
  'tests/input_hotplug_test.c',
  dependencies: input_hotplug_dep,
)
test('Wayland input hotplug state model', input_hotplug_test)

command_lib = static_library(
  'wtwm-command-lib',
  'src/command.c',
  include_directories: inc,
)
command_dep = declare_dependency(
  link_with: command_lib,
  include_directories: inc,
)

command_test = executable(
  'command-test',
  'tests/command_test.c',
  dependencies: command_dep,
)
test('twm command execution planning', command_test)

session_state_lib = static_library(
  'wtwm-session-state-lib',
  'src/session_state.c',
  include_directories: inc,
)
session_state_dep = declare_dependency(
  link_with: session_state_lib,
  include_directories: inc,
)

session_state_test = executable(
  'session-state-test',
  'tests/session_state_test.c',
  dependencies: session_state_dep,
)
test('portable compositor session state', session_state_test)

bindings_lib = static_library(
  'wtwm-bindings-lib',
  'src/bindings.c',
  include_directories: inc,
  dependencies: config_dep,
)
bindings_dep = declare_dependency(
  link_with: bindings_lib,
  include_directories: inc,
  dependencies: config_dep,
)

bindings_test = executable(
  'bindings-test',
  'tests/bindings_test.c',
  dependencies: bindings_dep,
)
test('twm input binding selection', bindings_test)

lifecycle_model_lib = static_library(
  'wtwm-lifecycle-model-lib',
  'src/lifecycle_model.c',
  include_directories: inc,
)
lifecycle_model_dep = declare_dependency(
  link_with: lifecycle_model_lib,
  include_directories: inc,
)

lifecycle_model_test = executable(
  'lifecycle-model-test',
  'tests/lifecycle_model_test.c',
  dependencies: lifecycle_model_dep,
)
test('randomized lifecycle and stacking model', lifecycle_model_test)

focus_stack_lib = static_library(
  'wtwm-focus-stack-lib',
  'src/focus_stack.c',
  include_directories: inc,
)
focus_stack_dep = declare_dependency(
  link_with: focus_stack_lib,
  include_directories: inc,
)

focus_stack_test = executable(
  'focus-stack-test',
  'tests/focus_stack_test.c',
  dependencies: focus_stack_dep,
)
test('twm focus contexts and stacking model', focus_stack_test)
test(
  'focus contexts and stacking runtime contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_focus_stack_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)

geometry_test = executable(
  'geometry-test',
  'tests/geometry_test.c',
  dependencies: geometry_dep,
)
test('twm geometry and size constraints', geometry_test)
test(
  'geometry runtime wiring contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_geometry_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'wtwm Xwayland geometry matrix contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_wtwm_geometry_matrix.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)

config_tool = executable(
  'wtwm-config',
  'src/config_check.c',
  dependencies: config_dep,
  install: true,
)

config_test = executable(
  'config-test',
  'tests/config_test.c',
  dependencies: config_dep,
)
test(
  'twmrc parser',
  config_test,
  env: ['WTWM_SOURCE_ROOT=' + meson.project_source_root()],
)

config_malformed_test = executable(
  'config-malformed-test',
  'tests/config_malformed_test.c',
  dependencies: config_dep,
)
test('twmrc malformed input', config_malformed_test, timeout: 30)
test(
  'twmrc fuzzer contract',
  find_program('sh'),
  args: [
    files('tests/fuzz/run_config_fuzzer.sh'),
    '--validate-only',
    meson.project_source_root(),
  ],
)

test_control_protocol_lib = static_library(
  'wtwm-test-control-protocol',
  'src/test_control.c',
  include_directories: include_directories('src'),
)
test_control_protocol_dep = declare_dependency(
  link_with: test_control_protocol_lib,
  include_directories: include_directories('src'),
)
test_control_protocol_test = executable(
  'test-control-protocol-test',
  'tests/integration/test_control_protocol_test.c',
  dependencies: test_control_protocol_dep,
)
test('test control protocol', test_control_protocol_test)
test(
  'deterministic event trace contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_event_trace.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'move and resize runtime wiring contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_move_resize_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'test control synthetic seat contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_test_control_seat.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'build platform contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/platform/validate_build_platforms.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'session backend entrypoints',
  find_program('sh'),
  args: [files('tests/platform/session-entrypoints-test.sh')],
)
test(
  'session launcher',
  find_program('sh'),
  args: [files('tests/platform/session-launcher-test.sh')],
)
test(
  'package isolation contract',
  find_program('sh'),
  args: [files('tests/platform/package-isolation-test.sh')],
)
test(
  'headless stability runner contract',
  find_program('sh'),
  args: [files('tests/platform/headless-stability-runner-test.sh')],
)
test(
  'platform evidence contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/platform/validate-platform-evidence.py'),
    '--source-root', meson.project_source_root(),
    '--self-test',
  ],
)
test('packaged twmrc', config_tool, args: files('data/system.twmrc'))
test(
  'upstream reference freeze',
  find_program('sh'),
  args: [files('tests/reference/upstream_reference_test.sh'), meson.project_source_root()],
)
test(
  'upstream configuration inventory',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_upstream_inventory.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'parser fixture coverage',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_parser_fixture_coverage.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'parser fixture acceptance',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/compare_reference_parser.py'),
    '--source-root', meson.project_source_root(),
    '--config-tool', config_tool,
    '--wtwm-only',
  ],
)
test(
  'reference parser differential',
  find_program('sh'),
  args: [
    files('tests/reference/run_reference_parser_comparison.sh'),
    meson.project_source_root(),
    config_tool,
  ],
  timeout: 900,
)
test(
  'current implementation inventory',
  find_program('sh'),
  args: [files('tests/reference/current_implementation_audit_test.sh')],
)
test(
  'current feature coverage',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_feature_test_map.py'),
    '--source-root', meson.project_source_root(),
    '--config-tool', config_tool,
    '--self-test-tamper',
  ],
)
test(
  'compatibility ledger',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_compatibility_ledger.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
  timeout: 120,
)
test(
  'real-world twmrc corpus',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_twmrc_corpus.py'),
    '--source-root', meson.project_source_root(),
  ],
)
test(
  'real-world twmrc jim',
  config_tool,
  args: files('reference/upstream/twm-1.0.13.1/sample-twmrc/jim.twmrc'),
)
test(
  'real-world twmrc keith',
  config_tool,
  args: files('reference/upstream/twm-1.0.13.1/sample-twmrc/keith.twmrc'),
)
test(
  'real-world twmrc lemke',
  config_tool,
  args: files('reference/upstream/twm-1.0.13.1/sample-twmrc/lemke.twmrc'),
)
test(
  'reference X11 environment contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_environment.py'),
    '--source-root', meson.project_source_root(),
  ],
)
test(
  'reference twm build source',
  find_program('sh'),
  args: [
    files('tests/reference/build_reference_twm.sh'),
    '--validate-only', meson.project_source_root(),
  ],
)
test(
  'reference capture baselines',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_capture.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'reference geometry matrix contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_geometry_matrix.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'Milestone 4 geometry cross-product contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_geometry_cross_product.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'reference interaction source contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_interaction_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'reference action behavior contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_action_contract.py'),
    '--self-test-tamper',
  ],
)
test(
  'Milestone 8 restart translation contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_restart_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'Milestone 8 startwm handoff contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_startwm_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'Milestone 8 saved-state persistence contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_state_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'Milestone 8 X11 server resource no-op contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_x11_resource_noop_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'Milestone 8 legacy cut-buffer translation contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_cut_buffer_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'Milestone 8 X screen output mapping contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_screen_output_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'Milestone 8 warp-to-screen history contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_warp_screen_contract.py'),
    '--root', meson.project_source_root(),
    '--self-test',
  ],
)
test(
  'Milestone 8 output topology transaction contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_output_topology_contract.py'),
    '--root', meson.project_source_root(),
    '--self-test',
  ],
)
test(
  'Milestone 8 output restoration contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_output_restoration_contract.py'),
    '--root', meson.project_source_root(),
    '--self-test',
  ],
)
test(
  'Milestone 8 input hotplug contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_input_hotplug_contract.py'),
    '--root', meson.project_source_root(),
    '--self-test',
  ],
)
test(
  'Milestone 8 output placement and root contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_output_placement_contract.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'Milestone 8 f.colormap translation contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_reference_colormap_contract.py'),
    '--self-test',
  ],
)
test(
  'Milestone 8 colormap selection model',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/run_m8_colormap.py'),
    '--self-test-model',
  ],
)
test(
  'Milestone 8 cut-buffer state model',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/run_m8_cut_buffer.py'),
    '--self-test-model',
  ],
)
test(
  'Milestone 8 screen output mapping model',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/run_m8_screen_output.py'),
    '--self-test-model',
  ],
)
test(
  'Milestone 8 warp-to-screen history model',
  find_program('python3'),
  args: [
    '-B', files('tests/integration/run_m8_warp_screen.py'),
    '--self-test-model',
    '--config-tool', config_tool,
  ],
)
test(
  'Milestone 8 output placement/root model',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/run_m8_output_placement.py'),
    '--self-test-model',
  ],
)
test(
  'Milestone 8 output topology model',
  find_program('python3'),
  args: [
    '-B', files('tests/integration/run_m8_output_topology.py'),
    '--self-test-model',
    '--config-tool', config_tool,
  ],
)
test(
  'Milestone 8 output restoration model',
  find_program('python3'),
  args: [
    '-B', files('tests/integration/run_m8_output_restoration.py'),
    '--self-test-model',
    '--config-tool', config_tool,
  ],
)
test(
  'Milestone 8 input hotplug model',
  find_program('python3'),
  args: [
    '-B', files('tests/integration/run_m8_input_hotplug.py'),
    '--self-test-model',
    '--config-tool', config_tool,
  ],
)
test(
  'Milestone 6 action implementation matrix',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_m6_implementation_matrix.py'),
    '--source-root', meson.project_source_root(),
    '--config-tool', config_tool,
    '--self-test-tamper',
  ],
)
test(
  'Milestone 4 trace differential contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_m4_trace_differential.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'canonical X11 application manifest',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_canonical_x11_apps.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'canonical X11 runtime contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_canonical_clients.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'reference twm and wtwm X11 differential contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_x11_differential.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'Xwayland metadata mutation contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_xwayland_metadata_mutation.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'mixed native and Xwayland session contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_mixed_clients.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'adversarial client lifecycle contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_client_stress.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)
test(
  'randomized lifecycle model contract',
  find_program('python3'),
  args: [
    '-B',
    files('tests/integration/validate_lifecycle_model.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)

wlroots = dependency('wlroots-0.18', required: get_option('compositor'))
if wlroots.found()
  pangocairo = dependency('pangocairo')
  wayland_server = dependency('wayland-server')
  xkbcommon = dependency('xkbcommon')
  xcb = dependency('xcb')
  x11 = dependency('x11')
  wayland_protocols = dependency('wayland-protocols')
  wayland_scanner = find_program('wayland-scanner', native: true)
  xdg_shell_xml = wayland_protocols.get_variable(pkgconfig: 'pkgdatadir') / 'stable/xdg-shell/xdg-shell.xml'
  primary_selection_xml = wayland_protocols.get_variable(pkgconfig: 'pkgdatadir') / 'unstable/primary-selection/primary-selection-unstable-v1.xml'
  xdg_shell_header = custom_target(
    'xdg-shell-protocol-header',
    input: xdg_shell_xml,
    output: 'xdg-shell-protocol.h',
    command: [wayland_scanner, 'server-header', '@INPUT@', '@OUTPUT@'],
  )
  wtwm_compositor = executable(
    'wtwm',
    ['src/wtwm.c', 'src/text.c', xdg_shell_header],
    dependencies: [config_dep, geometry_dep, interaction_dep, placement_dep, wlroots, actions_dep, output_order_dep, output_restore_dep, input_hotplug_dep, command_dep, session_state_dep, bindings_dep, font_dep, color_dep, visual_dep, xbm_dep, pangocairo, wayland_server, xkbcommon, xcb, focus_stack_dep, icon_layout_dep, icon_manager_dep],
    install: true,
  )
  wtwm_test_compositor = executable(
    'wtwm-test-compositor',
    ['src/wtwm.c', 'src/text.c', 'src/test_control.c', xdg_shell_header],
    dependencies: [
      config_dep, geometry_dep, interaction_dep, placement_dep, actions_dep,
      output_order_dep, output_restore_dep, input_hotplug_dep,
      command_dep, session_state_dep, bindings_dep, wlroots, font_dep,
      color_dep, visual_dep, xbm_dep,
      focus_stack_dep, icon_layout_dep, icon_manager_dep,
      pangocairo,
      dependency('fontconfig'),
      wayland_server,
      xkbcommon,
      xcb,
    ],
    c_args: ['-DWTWM_TEST_CONTROL'],
    install: false,
  )
  wayland_client = dependency('wayland-client')
  xdg_shell_client_header = custom_target(
    'xdg-shell-client-protocol-header',
    input: xdg_shell_xml,
    output: 'xdg-shell-client-protocol.h',
    command: [wayland_scanner, 'client-header', '@INPUT@', '@OUTPUT@'],
  )
  xdg_shell_client_code = custom_target(
    'xdg-shell-client-protocol-code',
    input: xdg_shell_xml,
    output: 'xdg-shell-client-protocol.c',
    command: [wayland_scanner, 'private-code', '@INPUT@', '@OUTPUT@'],
  )
  primary_selection_client_header = custom_target(
    'primary-selection-client-protocol-header',
    input: primary_selection_xml,
    output: 'primary-selection-unstable-v1-client-protocol.h',
    command: [wayland_scanner, 'client-header', '@INPUT@', '@OUTPUT@'],
  )
  primary_selection_client_code = custom_target(
    'primary-selection-client-protocol-code',
    input: primary_selection_xml,
    output: 'primary-selection-unstable-v1-client-protocol.c',
    command: [wayland_scanner, 'private-code', '@INPUT@', '@OUTPUT@'],
  )
  wtwm_wayland_test_client = executable(
    'wtwm-wayland-test-client',
    [
      'tests/integration/wayland_test_client.c',
      xdg_shell_client_header,
      xdg_shell_client_code,
    ],
    dependencies: wayland_client,
    install: false,
  )
  wtwm_xdg_lifecycle_client = executable(
    'wtwm-xdg-lifecycle-client',
    [
      'tests/integration/xdg_lifecycle_client.c',
      xdg_shell_client_header,
      xdg_shell_client_code,
    ],
    dependencies: wayland_client,
    install: false,
  )
  wtwm_native_rules_client = executable(
    'wtwm-native-rules-client',
    [
      'tests/integration/native_rules_client.c',
      xdg_shell_client_header,
      xdg_shell_client_code,
    ],
    dependencies: wayland_client,
    install: false,
  )
  wtwm_selection_wayland_client = executable(
    'wtwm-selection-wayland-client',
    [
      'tests/integration/selection_wayland_client.c',
      xdg_shell_client_header,
      xdg_shell_client_code,
      primary_selection_client_header,
      primary_selection_client_code,
    ],
    dependencies: wayland_client,
    install: false,
  )
  wtwm_overlay_wayland_client = executable(
    'wtwm-overlay-wayland-client',
    [
      'tests/integration/overlay_wayland_client.c',
      xdg_shell_client_header,
      xdg_shell_client_code,
    ],
    dependencies: wayland_client,
    install: false,
  )
  wtwm_xwayland_probe = executable(
    'wtwm-xwayland-probe',
    'tests/integration/xwayland_probe.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_xwayland_bridge_client = executable(
    'wtwm-xwayland-bridge-client',
    'tests/integration/xwayland_bridge_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_m5_visual_client = executable(
    'wtwm-m5-visual-client',
    'tests/integration/m5_visual_client.c',
    dependencies: x11,
    install: false,
  )
  wtwm_m7_lifecycle_client = executable(
    'wtwm-m7-lifecycle-client',
    'tests/integration/m7_lifecycle_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_xwayland_geometry_matrix_client = executable(
    'wtwm-xwayland-geometry-matrix-client',
    'tests/integration/xwayland_geometry_matrix_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_interaction_x11_client = executable(
    'wtwm-interaction-x11-client',
    'tests/integration/interaction_x11_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_xwayland_placement_client = executable(
    'wtwm-xwayland-placement-client',
    'tests/integration/xwayland_placement_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_focus_stack_x11_client = executable(
    'wtwm-focus-stack-x11-client',
    'tests/integration/focus_stack_x11_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_xwayland_rules_client = executable(
    'wtwm-xwayland-rules-client',
    'tests/integration/xwayland_rules_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_selection_x11_client = executable(
    'wtwm-selection-x11-client',
    'tests/integration/selection_x11_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_overlay_x11_client = executable(
    'wtwm-overlay-x11-client',
    'tests/integration/overlay_x11_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_mixed_wayland_client = executable(
    'wtwm-mixed-wayland-client',
    [
      'tests/integration/mixed_wayland_client.c',
      xdg_shell_client_header,
      xdg_shell_client_code,
    ],
    dependencies: wayland_client,
    install: false,
  )
  wtwm_mixed_x11_client = executable(
    'wtwm-mixed-x11-client',
    'tests/integration/mixed_x11_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_input_hotplug_wayland_client = executable(
    'wtwm-input-hotplug-wayland-client',
    [
      'tests/integration/input_hotplug_wayland_client.c',
      xdg_shell_client_header,
      xdg_shell_client_code,
    ],
    dependencies: wayland_client,
    install: false,
  )
  wtwm_stress_wayland_client = executable(
    'wtwm-stress-wayland-client',
    [
      'tests/integration/stress_wayland_client.c',
      xdg_shell_client_header,
      xdg_shell_client_code,
    ],
    dependencies: wayland_client,
    install: false,
  )
  wtwm_stress_x11_client = executable(
    'wtwm-stress-x11-client',
    'tests/integration/stress_x11_client.c',
    dependencies: xcb,
    install: false,
  )
  wtwm_m8_colormap_client = executable(
    'wtwm-m8-colormap-client',
    'tests/integration/m8_colormap_client.c',
    dependencies: xcb,
    install: false,
  )
  canonical_xterm = find_program('xterm', required: true)
  canonical_xclock = find_program('xclock', required: true)
  canonical_xload = find_program('xload', required: true)
  canonical_emacs = find_program('emacs', required: true)
  canonical_dialog = find_program('dialog', required: true)
  integration_runner = find_program('python3')
  test(
    'canonical X11 applications under wtwm',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_canonical_x11_apps.py'),
      '--compositor', wtwm_test_compositor,
      '--icccm-client', wtwm_xwayland_bridge_client,
      '--xterm', canonical_xterm,
      '--xclock', canonical_xclock,
      '--xload', canonical_xload,
      '--emacs', canonical_emacs,
      '--dialog', canonical_dialog,
    ],
    timeout: 90,
    is_parallel: false,
  )
  test(
    'Xwayland lifecycle integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_xwayland_lifecycle.py'),
      '--compositor', wtwm_test_compositor,
      '--probe', wtwm_xwayland_probe,
    ],
    timeout: 60,
  )
  test(
    'Xwayland window-manager bridge integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_xwayland_bridge.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_xwayland_bridge_client,
    ],
    timeout: 60,
  )
  test(
    'wtwm Xwayland geometry matrix integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_xwayland_geometry_matrix.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_xwayland_geometry_matrix_client,
      '--source-root', meson.project_source_root(),
    ],
    timeout: 240,
    is_parallel: false,
  )
  test(
    'move and resize interaction integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_move_resize.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_interaction_x11_client,
    ],
    timeout: 120,
    is_parallel: false,
  )
  test(
    'initial placement integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_placement.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_xwayland_placement_client,
	  '--native-client', wtwm_xdg_lifecycle_client,
    ],
    timeout: 180,
    is_parallel: false,
  )
  test(
    'focus contexts and stacking integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_focus_stack.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_focus_stack_x11_client,
    ],
    timeout: 120,
    is_parallel: false,
  )
  test(
    'Milestone 6 actions and bindings integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m6_actions.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_focus_stack_x11_client,
    ],
    timeout: 120,
    is_parallel: false,
  )
  test(
    'Milestone 7 icons and icon managers integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m7_icons.py'),
      '--compositor', wtwm_test_compositor,
      '--bridge-client', wtwm_xwayland_bridge_client,
      '--visual-client', wtwm_m5_visual_client,
    ],
    timeout: 120,
    is_parallel: false,
  )
  test(
    'Milestone 8 in-place restart integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_restart.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_stress_wayland_client,
      '--x11-client', wtwm_stress_x11_client,
    ],
    timeout: 120,
    is_parallel: false,
  )
  test(
    'Milestone 8 safe startwm handoff integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_startwm.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_stress_wayland_client,
      '--x11-client', wtwm_stress_x11_client,
    ],
    timeout: 120,
    is_parallel: false,
  )
  test(
    'Milestone 8 saved session state integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_session_state.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_stress_wayland_client,
      '--x11-client', wtwm_stress_x11_client,
    ],
    timeout: 180,
    is_parallel: false,
  )
  test(
    'Milestone 8 X11 server resource no-op integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_noop_options.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_stress_wayland_client,
      '--x11-client', wtwm_stress_x11_client,
    ],
    timeout: 360,
    is_parallel: false,
  )
  test(
    'Milestone 8 Xwayland and native colormap integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_colormap.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_stress_wayland_client,
      '--x11-client', wtwm_m8_colormap_client,
    ],
    timeout: 120,
    is_parallel: false,
  )
  test(
    'Milestone 8 Wayland and Xwayland cut-buffer integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_cut_buffer.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_selection_wayland_client,
      '--x11-client', wtwm_selection_x11_client,
    ],
    timeout: 180,
    is_parallel: false,
  )
  test(
    'Milestone 8 X screen and Wayland output mapping integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_screen_output.py'),
      '--compositor', wtwm_test_compositor,
    ],
    timeout: 180,
    is_parallel: false,
  )
  test(
    'Milestone 8 warp-to-screen history integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_warp_screen.py'),
      '--compositor', wtwm_test_compositor,
      '--config-tool', config_tool,
    ],
    timeout: 180,
    is_parallel: false,
  )
  test(
    'Milestone 8 output-aware placement/root integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_output_placement.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_xwayland_placement_client,
      '--native-client', wtwm_stress_wayland_client,
    ],
    timeout: 180,
    is_parallel: false,
  )
  test(
    'Milestone 8 output topology transactions',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_output_topology.py'),
      '--compositor', wtwm_test_compositor,
      '--config-tool', config_tool,
      '--wayland-client', wtwm_stress_wayland_client,
      '--x11-client', wtwm_stress_x11_client,
    ],
    timeout: 180,
    is_parallel: false,
  )
  test(
    'Milestone 8 output disappearance restoration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_output_restoration.py'),
      '--compositor', wtwm_test_compositor,
      '--config-tool', config_tool,
      '--wayland-client', wtwm_stress_wayland_client,
      '--x11-client', wtwm_stress_x11_client,
      '--x11-family-client', wtwm_focus_stack_x11_client,
    ],
    timeout: 240,
    is_parallel: false,
  )
  test(
    'Milestone 8 input hotplug integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_m8_input_hotplug.py'),
      '--compositor', wtwm_test_compositor,
      '--config-tool', config_tool,
      '--wayland-observer', wtwm_input_hotplug_wayland_client,
      '--x11-client', wtwm_mixed_x11_client,
    ],
    timeout: 300,
    is_parallel: false,
  )
  test(
    'Xwayland window-list rules integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_xwayland_rules.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_xwayland_rules_client,
    ],
    timeout: 60,
  )
  test(
    'Wayland and Xwayland selection bridge integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_selection_bridge.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_selection_wayland_client,
      '--x11-client', wtwm_selection_x11_client,
    ],
    timeout: 90,
  )
  test(
    'mixed native and Xwayland client integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_mixed_clients.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_mixed_wayland_client,
      '--x11-client', wtwm_mixed_x11_client,
    ],
    timeout: 90,
  )
  test(
    'adversarial client lifecycle integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_client_stress.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_stress_wayland_client,
      '--x11-client', wtwm_stress_x11_client,
    ],
    timeout: 120,
    is_parallel: false,
  )
  test(
    'randomized lifecycle and stacking integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_randomized_lifecycle.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_stress_wayland_client,
      '--x11-client', wtwm_stress_x11_client,
    ],
    timeout: 180,
    is_parallel: false,
  )
  test(
    'xdg-shell lifecycle integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_xdg_lifecycle.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_xdg_lifecycle_client,
    ],
    timeout: 60,
  )
  test(
    'popup and unmanaged overlay stacking integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_overlay_stacking.py'),
      '--compositor', wtwm_test_compositor,
      '--wayland-client', wtwm_overlay_wayland_client,
      '--x11-client', wtwm_overlay_x11_client,
    ],
    timeout: 90,
  )
  test(
    'native window-list mapping integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_native_rules.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_native_rules_client,
    ],
    timeout: 60,
  )
  test(
    'headless compositor integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_compositor.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_wayland_test_client,
    ],
    timeout: 60,
  )
  test(
    'headless compositor stability (100 runs)',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_compositor.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_wayland_test_client,
      '--repeat', '100',
    ],
    timeout: 600,
    is_parallel: false,
  )
  test(
    'nested Wayland compositor integration',
    integration_runner,
    args: [
      '-B', files('tests/integration/run_compositor.py'),
      '--compositor', wtwm_test_compositor,
      '--client', wtwm_wayland_test_client,
      '--nested',
    ],
    timeout: 60,
  )
  install_data(
    'data/wtwm.desktop',
    install_dir: get_option('datadir') / 'wayland-sessions',
  )
  install_man('data/wtwm.1')
elif get_option('compositor').enabled()
  error('wlroots 0.18 is required when -Dcompositor=enabled')
else
  warning('wlroots 0.18 was not found; building wtwm-config and parser tests only')
endif

install_data(
  'data/system.twmrc',
  install_dir: get_option('datadir') / 'wtwm',
)
install_data(
  'scripts/platform/wtwm-session',
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)
install_man('data/wtwm-config.1')
