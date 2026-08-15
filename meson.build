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
config_lib = static_library(
  'wtwm-config-lib',
  'src/config.c',
  include_directories: inc,
  c_args: config_args,
)
config_dep = declare_dependency(
  link_with: config_lib,
  include_directories: inc,
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
test('twmrc parser', config_test)

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
  'canonical X11 application manifest',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_canonical_x11_apps.py'),
    '--source-root', meson.project_source_root(),
    '--self-test-tamper',
  ],
)

wlroots = dependency('wlroots-0.18', required: get_option('compositor'))
if wlroots.found()
  pangocairo = dependency('pangocairo')
  wayland_server = dependency('wayland-server')
  xkbcommon = dependency('xkbcommon')
  wayland_protocols = dependency('wayland-protocols')
  wayland_scanner = find_program('wayland-scanner', native: true)
  xdg_shell_xml = wayland_protocols.get_variable(pkgconfig: 'pkgdatadir') / 'stable/xdg-shell/xdg-shell.xml'
  xdg_shell_header = custom_target(
    'xdg-shell-protocol-header',
    input: xdg_shell_xml,
    output: 'xdg-shell-protocol.h',
    command: [wayland_scanner, 'server-header', '@INPUT@', '@OUTPUT@'],
  )
  wtwm_compositor = executable(
    'wtwm',
    ['src/wtwm.c', 'src/text.c', xdg_shell_header],
    dependencies: [config_dep, wlroots, pangocairo, wayland_server, xkbcommon],
    install: true,
  )
  wtwm_test_compositor = executable(
    'wtwm-test-compositor',
    ['src/wtwm.c', 'src/text.c', 'src/test_control.c', xdg_shell_header],
    dependencies: [config_dep, wlroots, pangocairo, wayland_server, xkbcommon],
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
  integration_runner = find_program('python3')
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
