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
  'compatibility ledger',
  find_program('python3'),
  args: [
    '-B',
    files('tests/reference/validate_compatibility_ledger.py'),
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
  executable(
    'wtwm',
    ['src/wtwm.c', 'src/text.c', xdg_shell_header],
    dependencies: [config_dep, wlroots, pangocairo, wayland_server, xkbcommon],
    install: true,
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
install_man('data/wtwm-config.1')
