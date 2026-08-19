/* SPDX-License-Identifier: MIT */
#include <wtwm/command.h>

#include <assert.h>
#include <stdio.h>
#include <string.h>

struct direct_case {
	const char *command;
	size_t argc;
	const char *argv[8];
};

static int failures;

static void fail(const char *group, size_t index, const char *detail) {
	fprintf(stderr, "%s case %zu: %s\n", group, index, detail);
	++failures;
}

static void test_direct_commands(void) {
	static const struct direct_case cases[] = {
		{"xterm", 1, {"xterm"}},
		{"  xterm\t-name  twm  ", 3, {"xterm", "-name", "twm"}},
		{"prog 'two words' plain", 3, {"prog", "two words", "plain"}},
		{"prog \"two words\" plain", 3, {"prog", "two words", "plain"}},
		{"prog one\\ two", 2, {"prog", "one two"}},
		{"prog '' \"\"", 3, {"prog", "", ""}},
		{"prog a''b c\"\"d", 3, {"prog", "ab", "cd"}},
		{"prog 'a\\b'", 2, {"prog", "a\\b"}},
		{"prog \"a\\qb\"", 2, {"prog", "a\\qb"}},
		{"prog \"a\\\"b\"", 2, {"prog", "a\"b"}},
		{"prog \"a\\\\b\"", 2, {"prog", "a\\b"}},
		{"prog \\$ \\` \\* \\? \\[ \\] \\~", 8,
			{"prog", "$", "`", "*", "?", "[", "]", "~"}},
		{"prog \\; \\& \\| \\< \\> \\( \\)", 8,
			{"prog", ";", "&", "|", "<", ">", "(", ")"}},
		{"prog \"\\$\\`\"", 2, {"prog", "$`"}},
		{"prog ';&|<>$`*?[]~#()'", 2, {"prog", ";&|<>$`*?[]~#()"}},
		{"prog \";&|<>*?[]~#()\"", 2, {"prog", ";&|<>*?[]~#()"}},
		{"prog foo#bar", 2, {"prog", "foo#bar"}},
		{"prog name~suffix ]", 3, {"prog", "name~suffix", "]"}},
		{"prog line\\\ncontinuation", 2, {"prog", "linecontinuation"}},
		{"prog \"line\\\ncontinuation\"", 2, {"prog", "linecontinuation"}},
		{"prog 'line\ninside'", 2, {"prog", "line\ninside"}},
		{"prog \"line\ninside\"", 2, {"prog", "line\ninside"}},
		{"/bin/echo echo", 2, {"/bin/echo", "echo"}},
		{"env NAME=value program", 3, {"env", "NAME=value", "program"}},
		{"prog {one,two}", 2, {"prog", "{one,two}"}},
		{"prog carriage\rreturn", 2, {"prog", "carriage\rreturn"}},
	};

	for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		struct wtwm_command_plan plan;
		enum wtwm_command_result result =
			wtwm_command_plan_create(cases[index].command, &plan);
		if (result != WTWM_COMMAND_OK) {
			fail("direct", index, wtwm_command_result_message(result));
			continue;
		}
		if (plan.mode != WTWM_COMMAND_DIRECT) fail("direct", index, "used shell");
		if (strcmp(plan.command, cases[index].command) != 0)
			fail("direct", index, "did not preserve source command");
		if (plan.argc != cases[index].argc) {
			fail("direct", index, "wrong argument count");
		} else {
			for (size_t argument = 0; argument < plan.argc; ++argument) {
				if (strcmp(plan.argv[argument], cases[index].argv[argument]) != 0)
					fail("direct", index, "wrong argument value");
			}
		}
		if (plan.argv == NULL || plan.argv[plan.argc] != NULL)
			fail("direct", index, "argv is not NULL-terminated");
		wtwm_command_plan_destroy(&plan);
	}
}

static void test_shell_commands(void) {
	static const char *const cases[] = {
		"xterm &", "one; two", "one && two", "one || two", "one | two",
		"  one | two  ",
		"one > file", "one < file", "one ( two )", "$(program)",
		"`program`", "program $HOME", "program ${HOME}", "program *.c",
		"program file?.c", "program [ab]", "program ~", "program ~/file",
		"# comment", "program argument # comment", "program\nnext",
		"NAME=value program", "_NAME9=value", "cd /tmp", "exec program",
		"exit 0", "echo text", "printf %s text", "test -f file", "true",
		"false", "if program", "while program", "time program", ". file", ": argument",
		"{ program; }", "program \"$HOME\"", "program \"`other`\"",
	};

	for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		struct wtwm_command_plan plan;
		enum wtwm_command_result result = wtwm_command_plan_create(cases[index], &plan);
		if (result != WTWM_COMMAND_OK) {
			fail("shell", index, wtwm_command_result_message(result));
			continue;
		}
		if (plan.mode != WTWM_COMMAND_SHELL) fail("shell", index, "used direct mode");
		if (strcmp(plan.command, cases[index]) != 0)
			fail("shell", index, "did not preserve exact command");
		if (plan.argc != 0 || plan.argv != NULL)
			fail("shell", index, "shell plan exposed direct arguments");
		wtwm_command_plan_destroy(&plan);
	}
}

static void test_malformed_commands(void) {
	static const struct {
		const char *command;
		enum wtwm_command_result expected;
	} cases[] = {
		{"", WTWM_COMMAND_EMPTY},
		{"   \t ", WTWM_COMMAND_EMPTY},
		{"'", WTWM_COMMAND_UNTERMINATED_SINGLE_QUOTE},
		{"program 'value", WTWM_COMMAND_UNTERMINATED_SINGLE_QUOTE},
		{"\"", WTWM_COMMAND_UNTERMINATED_DOUBLE_QUOTE},
		{"program \"value", WTWM_COMMAND_UNTERMINATED_DOUBLE_QUOTE},
		{"program \\", WTWM_COMMAND_TRAILING_BACKSLASH},
		{"program \"value\\", WTWM_COMMAND_TRAILING_BACKSLASH},
		{"program | next '", WTWM_COMMAND_UNTERMINATED_SINGLE_QUOTE},
		{"program $HOME \"", WTWM_COMMAND_UNTERMINATED_DOUBLE_QUOTE},
		{"program && next \\", WTWM_COMMAND_TRAILING_BACKSLASH},
	};

	for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		struct wtwm_command_plan plan;
		enum wtwm_command_result result =
			wtwm_command_plan_create(cases[index].command, &plan);
		if (result != cases[index].expected)
			fail("malformed", index, "wrong diagnostic");
	}

	struct wtwm_command_plan plan;
	if (wtwm_command_plan_create(NULL, &plan) != WTWM_COMMAND_INVALID_ARGUMENT)
		fail("malformed", sizeof(cases) / sizeof(cases[0]), "accepted NULL command");
	if (wtwm_command_plan_create("program", NULL) != WTWM_COMMAND_INVALID_ARGUMENT)
		fail("malformed", sizeof(cases) / sizeof(cases[0]) + 1, "accepted NULL plan");
	wtwm_command_plan_destroy(NULL);
}

static void test_destroy_resets_plan(void) {
	struct wtwm_command_plan plan;
	if (wtwm_command_plan_create("program argument", &plan) != WTWM_COMMAND_OK) {
		fail("destroy", 0, "could not make plan");
		return;
	}
	wtwm_command_plan_destroy(&plan);
	if (plan.command != NULL || plan.argv != NULL || plan.argc != 0 ||
			plan.mode != WTWM_COMMAND_DIRECT)
		fail("destroy", 0, "plan was not reset");
}

static void test_safe_handoff_planning(void) {
	struct {
		const char *command;
		const char *running_program;
		enum wtwm_handoff_result expected;
		const char *config_path;
	} cases[] = {
		{"wtwm", "/usr/bin/wtwm", WTWM_HANDOFF_RELOAD, NULL},
		{"./wtwm -f alternate.twmrc", "/usr/bin/wtwm",
			WTWM_HANDOFF_RELOAD_CONFIG, "alternate.twmrc"},
		{"/opt/wtwm -f'alternate config'", "wtwm",
			WTWM_HANDOFF_RELOAD_CONFIG, "alternate config"},
		{"wtwm -fnext.twmrc", "wtwm",
			WTWM_HANDOFF_RELOAD_CONFIG, "next.twmrc"},
		{"other-wm", "wtwm", WTWM_HANDOFF_UNSUPPORTED, NULL},
		{"wtwm && true", "wtwm", WTWM_HANDOFF_UNSUPPORTED, NULL},
		{"wtwm -d", "wtwm", WTWM_HANDOFF_UNSUPPORTED, NULL},
		{"wtwm -f", "wtwm", WTWM_HANDOFF_UNSUPPORTED, NULL},
		{"wtwm -f ''", "wtwm", WTWM_HANDOFF_UNSUPPORTED, NULL},
		{"wtwm", "wtwm-test-compositor", WTWM_HANDOFF_UNSUPPORTED, NULL},
	};
	for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
		struct wtwm_command_plan plan;
		assert(wtwm_command_plan_create(cases[i].command, &plan) ==
			WTWM_COMMAND_OK);
		const char *config_path = "unchanged";
		enum wtwm_handoff_result result = wtwm_command_handoff(
			&plan, cases[i].running_program, &config_path);
		assert(result == cases[i].expected);
		if (cases[i].config_path == NULL) assert(config_path == NULL);
		else assert(config_path != NULL &&
			strcmp(config_path, cases[i].config_path) == 0);
		wtwm_command_plan_destroy(&plan);
	}
	const char *config_path = "unchanged";
	assert(wtwm_command_handoff(NULL, "wtwm", &config_path) ==
		WTWM_HANDOFF_UNSUPPORTED && config_path == NULL);
}

int main(void) {
	test_direct_commands();
	test_shell_commands();
	test_malformed_commands();
	test_destroy_resets_plan();
	test_safe_handoff_planning();
	return failures == 0 ? 0 : 1;
}
