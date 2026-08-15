# Configuration fuzzer

`config_fuzzer.c` drives both fresh parses and transactional reloads through
libFuzzer. The runner seeds mutations with the complete grammar fixture,
malformed fixtures, packaged defaults, and all frozen upstream examples.

The pinned Linux CI run executes 100,000 cases with AddressSanitizer,
LeakSanitizer, UndefinedBehaviorSanitizer, a two-second per-input timeout, and
an 8 KiB mutation limit:

```sh
sh tests/fuzz/run_config_fuzzer.sh "$PWD" /tmp/wtwm-config-fuzz 100000
```

On platforms whose AddressSanitizer lacks leak detection, set
`WTWM_FUZZ_ASAN_OPTIONS=detect_leaks=0:abort_on_error=1:halt_on_error=1` for a
local smoke run. Linux CI always leaves leak detection enabled.
