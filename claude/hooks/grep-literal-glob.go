// Advisory Claude PreToolUse guard, not a shell parser or security boundary.
// It checks direct grep commands with literal include/exclude globs, and test,
// typecheck or lint commands piped straight into grep, rg or head without
// pipefail: the pipe drops the check's exit status and can hide error lines.
// Unsupported substitutions, grouping and malformed shell input fail open.
// Contract: JSON stdin; silent exit 0 allows, exit 2 + stderr blocks PreToolUse.
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

// Tokenize words, separators and redirects without expanding or executing text.
// A substitution inside double quotes stays one opaque, non-literal word.
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

		value := word{literal: true}
		var quote rune
		for i < len(source) {
			char = source[i]
			if quote == 0 && strings.ContainsRune(" \t\r\n;&|<>", char) {
				break
			}
			substitution := char == '$' && i+1 < len(source) && (source[i+1] == '(' || source[i+1] == '{')
			if quote == '"' && substitution {
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

func unsafeOption(words []word) string {
	if len(words) == 0 {
		return ""
	}
	switch string(words[0].text) {
	case "grep", "/bin/grep", "/usr/bin/grep":
	default:
		return ""
	}
	for i := 1; i < len(words); i++ {
		value := words[i]
		if !value.literal {
			continue
		}
		text := string(value.text)
		switch text {
		case "--":
			return ""
		case "-e", "-f", "--regexp", "--file", "-m", "--max-count",
			"-A", "-B", "-C", "--after-context", "--before-context", "--context",
			"-d", "-D", "--directories", "--devices", "--label", "--binary-files":
			i++
			continue
		}
		// Unknown short-option clusters may consume the next argument (-ne, -rf).
		if shortOptionCluster.MatchString(text) {
			return ""
		}
		for _, option := range []string{"--include", "--exclude"} {
			if text == option {
				i++
				if i < len(words) && words[i].literal && words[i].glob(0) {
					return option
				}
			} else if strings.HasPrefix(text, option+"=") && value.glob(len(option)+1) {
				return option
			}
		}
	}
	return ""
}

var (
	assignment  = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*=`)
	checkScript = regexp.MustCompile(`^(test|typecheck|lint|check)(:|$)`)
	checkTools  = map[string]bool{"vitest": true, "tsc": true, "eslint": true, "oxlint": true, "jest": true}
	filters     = map[string]bool{"grep": true, "egrep": true, "fgrep": true, "rg": true, "head": true}
)

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
// assignments and the npx, n exec, timeout, time, nice, env or command wrappers.
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
	if checkTools[tool] {
		return true
	}
	switch tool {
	case "npm", "pnpm", "yarn", "bun":
		var args []string
		for _, w := range words[i+1:] {
			if text := string(w.text); !strings.HasPrefix(text, "-") {
				args = append(args, text)
			}
		}
		if len(args) > 0 && (args[0] == "run" || args[0] == "run-script") {
			args = args[1:]
		}
		return len(args) > 0 && (args[0] == "t" || checkScript.MatchString(args[0]))
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
		"grep the printed log path if you need specific lines. Piping into tail or set -o pipefail "+
		"is also accepted. The command was not executed or rewritten.\n", filter)
}

func detect(source string) string {
	parts, supported := tokens(source)
	if !supported {
		return ""
	}
	pipefail := false
	for _, part := range parts {
		if text := string(part.word.text); strings.Contains(text, "pipefail") ||
			strings.Contains(strings.ToUpper(text), "PIPESTATUS") {
			pipefail = true
		}
	}
	var command []word
	redirect, fromCheck := false, false
	for _, part := range append(parts, token{operator: "\n"}) {
		switch part.operator {
		case "":
			if redirect {
				redirect = false
			} else {
				command = append(command, part.word)
			}
		case ";", "&", "|", "&&", "||", "\n":
			if found := unsafeOption(command); found != "" {
				return grepMessage(found)
			}
			if fromCheck && !pipefail && len(command) > 0 && filters[name(command[0])] {
				return pipeMessage(name(command[0]))
			}
			fromCheck = part.operator == "|" && checkCommand(command)
			command = nil
			redirect = false
		default:
			redirect = true
		}
	}
	return ""
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
	if message := detect(command); message != "" {
		fmt.Fprint(os.Stderr, message)
		return 2
	}
	return 0
}

func main() {
	os.Exit(run())
}
