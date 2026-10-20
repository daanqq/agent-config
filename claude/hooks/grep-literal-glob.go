// Advisory Claude PreToolUse guard, not a shell parser or security boundary.
// Only direct grep commands with literal include/exclude values are checked.
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

// Tokenize words, separators and redirects without expanding or executing text.
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

func detect(source string) string {
	parts, supported := tokens(source)
	if !supported {
		return ""
	}
	var command []word
	redirect := false
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
				return found
			}
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
	if option := detect(command); option != "" {
		fmt.Fprintf(os.Stderr, "Unquoted glob in literal grep %s argument. Quote the pattern "+
			"(for example %s='*.json') or use the search tool / rg -g '*.json'. "+
			"The command was not executed or rewritten.\n", option, option)
		return 2
	}
	return 0
}

func main() {
	os.Exit(run())
}
