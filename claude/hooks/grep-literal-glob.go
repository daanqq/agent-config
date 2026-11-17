// Advisory Claude PreToolUse guard, not a shell parser or security boundary.
// It quotes unquoted literal include/exclude globs of direct grep commands
// (blocking the command when a partly quoted glob cannot be quoted safely), and checks test,
// typecheck or lint commands piped straight into grep, rg or head without
// pipefail or a PIPESTATUS read in the very next command: the pipe drops the
// check's exit status and can hide error lines.
// It also rejects rm with an unquoted glob over run-check log directories,
// which are shared by parallel sessions in the system temporary directory,
// and git worktree prune without --dry-run, which drops records of every
// missing worktree of the repository, not only the agent's own.
// Unsupported substitutions, grouping and malformed shell input fail open.
// Contract: JSON stdin; silent exit 0 allows, exit 0 + JSON stdout with
// updatedInput and no permissionDecision rewrites the command and keeps the
// normal permission flow, exit 2 + stderr blocks PreToolUse.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"
)

type word struct {
	text    []rune
	active  []bool
	literal bool
	// start and end are rune offsets of the word in the source command.
	start, end int
}

func (w word) glob(start int) bool {
	for i := start; i < len(w.text); i++ {
		if !w.active[i] {
			continue
		}
		switch w.text[i] {
		case '*', '?':
			return true
		case '[':
			for end := i + 2; end < len(w.text); end++ {
				if w.text[end] == ']' {
					if w.active[end] {
						return true
					}
					break
				}
			}
		}
	}
	return false
}

type token struct {
	word     word
	operator string
}

type heredoc struct {
	ending string
	tabs   bool
}

// skipSubstitution returns the index after the $(...) or ${...} starting at i,
// or -1 when its end cannot be found without a real shell parser.
func skipSubstitution(source []rune, i int) int {
	open, closing := source[i+1], ')'
	if open == '{' {
		closing = '}'
	}
	depth := 1
	for j := i + 2; j < len(source); j++ {
		switch char := source[j]; {
		case char == '\\':
			j++
		case char == '`':
			return -1
		case char == '\'':
			for j++; j < len(source) && source[j] != '\''; j++ {
			}
			if j == len(source) {
				return -1
			}
		case char == '"':
			for j++; j < len(source) && source[j] != '"'; j++ {
				if source[j] == '\\' {
					j++
				} else if source[j] == '`' {
					return -1
				} else if source[j] == '$' && j+1 < len(source) && (source[j+1] == '(' || source[j+1] == '{') {
					end := skipSubstitution(source, j)
					if end < 0 {
						return -1
					}
					j = end - 1
				}
			}
			if j >= len(source) {
				return -1
			}
		case char == open:
			depth++
		case char == closing:
			depth--
			if depth == 0 {
				return j + 1
			}
		}
	}
	return -1
}

// assignmentPrefix reports whether the word read so far starts with an unquoted
// NAME=. Bash does not word-split an assignment value, so a substitution there
// stays one word even without quotes, as in `V=$(cat .nvmrc); n exec $V ...`.
func assignmentPrefix(value word) bool {
	prefix := assignment.FindStringIndex(string(value.text))
	if prefix == nil {
		return false
	}
	// NAME= is ASCII, so its byte length is also its length in runes.
	for _, active := range value.active[:prefix[1]] {
		if !active {
			return false
		}
	}
	return true
}

// Tokenize words, separators and redirects without expanding or executing text.
// A substitution inside double quotes or an assignment value stays one opaque,
// non-literal word.
// Heredoc bodies are opaque; false means the entire command is unsupported.
func tokens(command string) ([]token, bool) {
	source := []rune(command)
	var result []token
	var heredocs []heredoc
	delimiter := ""
	i := 0
	for i < len(source) {
		char := source[i]
		if strings.ContainsRune(" \t\r", char) {
			i++
			continue
		}
		if char == '#' {
			for i < len(source) && source[i] != '\n' {
				i++
			}
			continue
		}
		if char == '\n' {
			result = append(result, token{operator: "\n"})
			i++
			if delimiter != "" {
				return nil, false
			}
			for _, doc := range heredocs {
				for {
					end := i
					for end < len(source) && source[end] != '\n' {
						end++
					}
					line := string(source[i:end])
					i = end
					if i < len(source) {
						i++
					}
					if doc.tabs {
						line = strings.TrimLeft(line, "\t")
					}
					if line == doc.ending {
						break
					}
					if end == len(source) {
						return nil, false
					}
				}
			}
			heredocs = nil
			continue
		}
		if strings.ContainsRune("(){}", char) {
			return nil, false
		}
		if strings.ContainsRune(";&|<>", char) {
			operator := string(char)
			for _, candidate := range []string{"<<<", "<<-", "<<", ">>", "&&", "||", "&>", "<&", ">&"} {
				if i+len(candidate) <= len(source) && string(source[i:i+len(candidate)]) == candidate {
					operator = candidate
					break
				}
			}
			result = append(result, token{operator: operator})
			i += len(operator)
			if operator == "<<" || operator == "<<-" {
				delimiter = operator
			}
			continue
		}

		value := word{literal: true, start: i}
		var quote rune
		for i < len(source) {
			char = source[i]
			if quote == 0 && strings.ContainsRune(" \t\r\n;&|<>", char) {
				break
			}
			substitution := char == '$' && i+1 < len(source) && (source[i+1] == '(' || source[i+1] == '{')
			if quote == '"' && substitution || quote == 0 && substitution && assignmentPrefix(value) {
				end := skipSubstitution(source, i)
				if end < 0 {
					return nil, false
				}
				for ; i < end; i++ {
					value.text = append(value.text, source[i])
					value.active = append(value.active, false)
				}
				value.literal = false
				continue
			}
			if quote != '\'' && (char == '`' || substitution) {
				return nil, false
			}
			if quote == 0 && strings.ContainsRune("(){}", char) {
				return nil, false
			}
			if char == '\\' && quote != '\'' {
				if i+1 == len(source) {
					return nil, false
				}
				following := source[i+1]
				if following == '\n' {
					i += 2
					continue
				}
				if quote == 0 || strings.ContainsRune("$`\"\\", following) {
					value.text = append(value.text, following)
					value.active = append(value.active, false)
					i += 2
					continue
				}
			}
			if (char == '\'' || char == '"') && (quote == 0 || quote == char) {
				if quote == 0 {
					quote = char
				} else {
					quote = 0
				}
				i++
				continue
			}
			if char == '$' && quote != '\'' {
				value.literal = false
			}
			value.text = append(value.text, char)
			value.active = append(value.active, quote == 0)
			i++
		}
		if quote != 0 {
			return nil, false
		}
		value.end = i
		result = append(result, token{word: value})
		if delimiter != "" {
			if !value.literal {
				return nil, false
			}
			heredocs = append(heredocs, heredoc{ending: string(value.text), tabs: delimiter == "<<-"})
			delimiter = ""
		}
	}
	return result, len(heredocs) == 0 && delimiter == ""
}

var shortOptionCluster = regexp.MustCompile(`^-[^-].*[efmABCdD]$`)

type globOption struct {
	option string
	value  word
	inline bool // --include=GLOB rather than --include GLOB
}

// unsafeOptions returns the literal include/exclude arguments with an active glob.
func unsafeOptions(words []word) []globOption {
	var found []globOption
	if len(words) == 0 {
		return nil
	}
	switch string(words[0].text) {
	case "grep", "/bin/grep", "/usr/bin/grep":
	default:
		return nil
	}
	for i := 1; i < len(words); i++ {
		value := words[i]
		if !value.literal {
			continue
		}
		text := string(value.text)
		switch text {
		case "--":
			return found
		case "-e", "-f", "--regexp", "--file", "-m", "--max-count",
			"-A", "-B", "-C", "--after-context", "--before-context", "--context",
			"-d", "-D", "--directories", "--devices", "--label", "--binary-files":
			i++
			continue
		}
		// Unknown short-option clusters may consume the next argument (-ne, -rf).
		if shortOptionCluster.MatchString(text) {
			return nil
		}
		for _, option := range []string{"--include", "--exclude"} {
			if text == option {
				i++
				if i < len(words) && words[i].literal && words[i].glob(0) {
					found = append(found, globOption{option, words[i], false})
				}
			} else if strings.HasPrefix(text, option+"=") && value.glob(len(option)+1) {
				found = append(found, globOption{option, value, true})
			}
		}
	}
	return found
}

type edit struct {
	start, end int
	text       string
	option     string
}

// quoteEdit single-quotes the glob of a word written without any quotes or
// escapes; a partly quoted word is left to the agent.
func quoteEdit(found globOption) (edit, bool) {
	w := found.value
	if w.end-w.start != len(w.text) {
		return edit{}, false
	}
	for _, active := range w.active {
		if !active {
			return edit{}, false
		}
	}
	text := "'" + string(w.text) + "'"
	if found.inline {
		text = found.option + "='" + string(w.text[len(found.option)+1:]) + "'"
	}
	return edit{w.start, w.end, text, found.option}, true
}

func apply(source string, edits []edit) string {
	runes := []rune(source)
	var out []rune
	last := 0
	for _, e := range edits {
		out = append(append(out, runes[last:e.start]...), []rune(e.text)...)
		last = e.end
	}
	return string(append(out, runes[last:]...))
}

var (
	assignment  = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*=`)
	checkScript = regexp.MustCompile(`^(test|typecheck|type-check|ts-check|lint|check)(:|$)`)
	checkTools  = map[string]bool{"vitest": true, "tsc": true, "eslint": true, "oxlint": true, "jest": true}
	filters     = map[string]bool{"grep": true, "egrep": true, "fgrep": true, "rg": true, "head": true}
	infoFlags   = map[string]bool{"--help": true, "--version": true, "--rules": true}
	python      = regexp.MustCompile(`^python[0-9.]*$`)
	testScript  = regexp.MustCompile(`(^|[/._-])tests?([/._-]|$)`)
	shells      = map[string]bool{"bash": true, "sh": true, "zsh": true}
)

// shellTest reports a shell script whose path names it a test, such as
// test/allocation.test.sh or scripts/run-tests.sh.
func shellTest(w word) bool {
	text := string(w.text)
	return w.literal && strings.HasSuffix(text, ".sh") && testScript.MatchString(text)
}

func name(w word) string {
	text := string(w.text)
	return text[strings.LastIndex(text, "/")+1:]
}

func skipOptions(words []word, i int) int {
	for i < len(words) && strings.HasPrefix(string(words[i].text), "-") {
		i++
	}
	return i
}

// checkCommand reports a test, typecheck or lint run, also behind env
// assignments and the npx, n exec, mise exec, timeout, time, nice, env or command wrappers.
// Python counts only as python -m unittest, a shell script only by a test path.
func checkCommand(words []word) bool {
	i := 0
wrappers:
	for i < len(words) {
		switch tool := name(words[i]); {
		case words[i].literal && assignment.MatchString(string(words[i].text)):
			i++
		case tool == "npx" || tool == "time" || tool == "nice" || tool == "env" || tool == "command":
			i = skipOptions(words, i+1)
		case tool == "n" && i+1 < len(words) && string(words[i+1].text) == "exec":
			i += 3
		case tool == "mise" && i+1 < len(words) && (string(words[i+1].text) == "exec" || string(words[i+1].text) == "x"):
			// mise exec [options] [tool@version...] -- command; without -- the command is ambiguous.
			for i += 2; i < len(words) && string(words[i].text) != "--"; i++ {
			}
			i++
		case tool == "timeout":
			for i++; i < len(words) && strings.HasPrefix(string(words[i].text), "-"); i++ {
				if text := string(words[i].text); text == "-k" || text == "-s" {
					i++ // --kill-after and --signal take a separate value
				}
			}
			i++ // duration
		default:
			break wrappers
		}
	}
	if i >= len(words) || !words[i].literal {
		return false
	}
	tool := name(words[i])
	for _, w := range words[i+1:] {
		if infoFlags[string(w.text)] {
			return false // help, version or rule listings print text, not a check result
		}
	}
	if checkTools[tool] || shellTest(words[i]) {
		return true
	}
	if shells[tool] {
		j := skipOptions(words, i+1)
		return j < len(words) && shellTest(words[j])
	}
	if python.MatchString(tool) {
		// python [interpreter options] -m unittest; a script path ends the options.
		for j := i + 1; j < len(words); j++ {
			if text := string(words[j].text); text == "-m" {
				return j+1 < len(words) && string(words[j+1].text) == "unittest"
			} else if !strings.HasPrefix(text, "-") {
				return false
			}
		}
		return false
	}
	switch tool {
	case "npm", "pnpm", "yarn", "bun":
		var args []string
		for _, w := range words[i+1:] {
			if text := string(w.text); !strings.HasPrefix(text, "-") {
				args = append(args, text)
			}
		}
		if len(args) > 0 && (args[0] == "run" || args[0] == "run-script" || args[0] == "exec" || args[0] == "x" || args[0] == "dlx") {
			args = args[1:]
		}
		// yarn tsc, pnpm exec eslint and the like run the tool directly.
		return len(args) > 0 && (args[0] == "t" || checkScript.MatchString(args[0]) || checkTools[args[0]])
	}
	return false
}

func grepMessage(option string) string {
	return fmt.Sprintf("Unquoted glob in literal grep %s argument. Quote the pattern "+
		"(for example %s='*.json') or use the search tool / rg -g '*.json'. "+
		"The command was not executed or rewritten.\n", option, option)
}

func pipeMessage(filter string) string {
	return fmt.Sprintf("A test, typecheck or lint command piped into %s loses its exit status "+
		"and can drop error lines such as the Vitest Errors block. Run it through the runner, "+
		"which keeps the status and the full log and prints the tail: "+
		"python3 \"$HOME/.claude/skills/prove-it-works/scripts/run-check.py\" --tail 40 -- <check command>; "+
		"grep the printed log path if you need specific lines. Piping into tail, set -o pipefail "+
		"before the pipe, or reading ${PIPESTATUS[0]} in the very next command is also accepted. "+
		"The command was not executed or rewritten.\n", filter)
}

// sharedLogGlob reports rm over run-check-* log directories by an unquoted
// glob: run-check.py creates them in the shared temporary directory, so the
// glob also matches logs of other sessions.
func sharedLogGlob(words []word) bool {
	if len(words) == 0 || name(words[0]) != "rm" {
		return false
	}
	for _, w := range words[1:] {
		if strings.Contains(string(w.text), "run-check-") && w.glob(0) {
			return true
		}
	}
	return false
}

const sharedLogMessage = "rm with a glob over run-check-* also removes logs of other sessions: " +
	"run-check.py keeps them in the shared temporary directory. Remove only the directory " +
	"of the Log: path that your own run printed. The command was not executed or rewritten.\n"

// worktreePrune reports git [global options] worktree prune without -n or
// --dry-run, also behind env assignments.
func worktreePrune(words []word) bool {
	i := 0
	for i < len(words) && words[i].literal && assignment.MatchString(string(words[i].text)) {
		i++
	}
	if i >= len(words) || name(words[i]) != "git" {
		return false
	}
	for i++; i < len(words) && strings.HasPrefix(string(words[i].text), "-"); i++ {
		switch string(words[i].text) {
		case "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env":
			i++ // these global options take a separate value
		}
	}
	if i+1 >= len(words) || string(words[i].text) != "worktree" || string(words[i+1].text) != "prune" {
		return false
	}
	for _, w := range words[i+2:] {
		if text := string(w.text); text == "-n" || text == "--dry-run" {
			return false
		}
	}
	return true
}

const worktreePruneMessage = "git worktree prune drops the records of every missing worktree " +
	"of this repository, not only yours. Remove your own worktree with " +
	"git worktree remove <path>, or run git worktree prune --dry-run and leave the cleanup " +
	"to the user. The command was not executed or rewritten.\n"

// detect returns a blocking message, or the edits that quote unquoted
// include/exclude globs, in source order.
func detect(source string) (string, []edit) {
	parts, supported := tokens(source)
	if !supported {
		return "", nil
	}
	var edits []edit
	// pipefail covers only later pipes. PIPESTATUS holds only the last pipeline,
	// so it counts only in the command right after the filtered check pipeline.
	pipefail := false
	var command []word
	redirect, fromCheck := false, false
	lost, awaiting := "", ""
	for _, part := range append(parts, token{operator: "\n"}) {
		switch part.operator {
		case "":
			if strings.Contains(string(part.word.text), "pipefail") {
				pipefail = true
			}
			if redirect {
				redirect = false
			} else {
				command = append(command, part.word)
			}
		case ";", "&", "|", "&&", "||", "\n":
			if awaiting != "" && len(command) > 0 {
				if !readsPipestatus(command) {
					return pipeMessage(awaiting), nil
				}
				awaiting = ""
			}
			for _, found := range unsafeOptions(command) {
				fix, ok := quoteEdit(found)
				if !ok {
					return grepMessage(found.option), nil
				}
				edits = append(edits, fix)
			}
			if sharedLogGlob(command) {
				return sharedLogMessage, nil
			}
			if worktreePrune(command) {
				return worktreePruneMessage, nil
			}
			if fromCheck && !pipefail && len(command) > 0 && filters[name(command[0])] {
				lost = name(command[0])
			}
			if part.operator != "|" && lost != "" {
				awaiting, lost = lost, ""
			}
			fromCheck = part.operator == "|" && checkCommand(command)
			command = nil
			redirect = false
		default:
			redirect = true
		}
	}
	if awaiting != "" {
		return pipeMessage(awaiting), nil
	}
	return "", edits
}

func readsPipestatus(command []word) bool {
	for _, w := range command {
		if strings.Contains(string(w.text), "PIPESTATUS") {
			return true
		}
	}
	return false
}

// encoding/json replaces lone surrogates with U+FFFD, which could close a
// heredoc early. Treat malformed Unicode commands as unsupported instead.
func validUnicodeEscapes(raw json.RawMessage) bool {
	for i := 0; i < len(raw); i++ {
		if raw[i] != '\\' {
			continue
		}
		i++
		if i >= len(raw) || raw[i] != 'u' {
			continue
		}
		if i+4 >= len(raw) {
			return false
		}
		unit, err := strconv.ParseUint(string(raw[i+1:i+5]), 16, 16)
		if err != nil {
			return false
		}
		i += 4
		if unit >= 0xD800 && unit <= 0xDBFF {
			if i+6 >= len(raw) || raw[i+1] != '\\' || raw[i+2] != 'u' {
				return false
			}
			low, err := strconv.ParseUint(string(raw[i+3:i+7]), 16, 16)
			if err != nil || low < 0xDC00 || low > 0xDFFF {
				return false
			}
			i += 6
		} else if unit >= 0xDC00 && unit <= 0xDFFF {
			return false
		}
	}
	return true
}

func run() int {
	raw, err := io.ReadAll(os.Stdin)
	if err != nil || !utf8.Valid(raw) {
		return 0
	}
	var payload, input map[string]json.RawMessage
	var event, tool, command string
	if json.Unmarshal(raw, &payload) != nil ||
		json.Unmarshal(payload["hook_event_name"], &event) != nil || event != "PreToolUse" ||
		json.Unmarshal(payload["tool_name"], &tool) != nil || tool != "Bash" ||
		json.Unmarshal(payload["tool_input"], &input) != nil ||
		json.Unmarshal(input["command"], &command) != nil || !validUnicodeEscapes(input["command"]) {
		return 0
	}
	message, edits := detect(command)
	if message != "" {
		fmt.Fprint(os.Stderr, message)
		return 2
	}
	if len(edits) == 0 {
		return 0
	}
	rewritten := apply(command, edits)
	if again, more := detect(rewritten); again != "" || len(more) > 0 {
		fmt.Fprint(os.Stderr, grepMessage(edits[0].option))
		return 2
	}
	// updatedInput replaces the whole tool input, so the other fields are kept.
	input["command"], _ = json.Marshal(rewritten)
	output, err := json.Marshal(map[string]any{"hookSpecificOutput": map[string]any{
		"hookEventName": "PreToolUse",
		"updatedInput":  input,
		"additionalContext": "The grep-literal-glob hook single-quoted the unquoted " + edits[0].option +
			" glob before running the command (for example " + edits[0].option + "='*.json'). " +
			"Quote such globs yourself next time.",
	}})
	if err != nil {
		return 0
	}
	fmt.Println(string(output))
	return 0
}

func main() {
	os.Exit(run())
}
