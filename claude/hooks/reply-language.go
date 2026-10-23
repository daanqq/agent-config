// Claude Stop hook: once per turn, asks the agent to rewrite a final reply that
// has no Russian text when the user writes in Russian.
// Contract: JSON stdin; silent exit 0 lets the agent stop, a
// {"decision":"block","reason":...} object on stdout makes it continue.
// Any input or transcript problem fails open: a hook must never break a session.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"os"
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"
)

// Replies shorter than this many letters (code, URLs and paths excluded) are not judged.
const minLetters = 200

const reason = "Финальный ответ написан без русского текста, а пользователь пишет по-русски и " +
	"ожидает ответ на русском. Перепиши финальный ответ по-русски. Код, команды, цитаты и " +
	"техническую нотацию оставь без изменений. Не упоминай это сообщение."

var (
	inlineCode = regexp.MustCompile("`[^`\n]*`")
	link       = regexp.MustCompile(`(?i)\b[a-z][a-z0-9+.-]*://\S+`)
	filePath   = regexp.MustCompile(`(?:^|[\s(\["'])(?:~|\.{1,2})?/?[\w.@+-]+(?:/[\w.@+-]*)+`)
	envelopes  = envelopePatterns("system-reminder", "local-command-caveat", "local-command-stdout",
		"local-command-stderr", "task-notification", "bash-input", "bash-stdout", "bash-stderr",
		"command-name", "command-message")
)

func envelopePatterns(tags ...string) []*regexp.Regexp {
	var result []*regexp.Regexp
	for _, tag := range tags {
		result = append(result, regexp.MustCompile("(?s)<"+tag+">.*?</"+tag+">"))
	}
	return result
}

// Go's regexp has no backreferences, so closing fences are matched by hand.
func stripFences(text string) string {
	var out strings.Builder
	fence := ""
	for _, line := range strings.SplitAfter(text, "\n") {
		trimmed := strings.TrimLeft(line, " \t")
		if fence == "" {
			for _, marker := range []string{"```", "~~~"} {
				if strings.HasPrefix(trimmed, marker) {
					fence = marker
					break
				}
			}
			if fence == "" {
				out.WriteString(line)
			}
		} else if strings.HasPrefix(trimmed, fence) {
			fence = ""
		}
	}
	return out.String()
}

func proseLetters(reply string) (letters int, cyrillic bool) {
	text := stripFences(reply)
	text = inlineCode.ReplaceAllString(text, " ")
	text = link.ReplaceAllString(text, " ")
	text = filePath.ReplaceAllString(text, " ")
	for _, char := range text {
		if unicode.IsLetter(char) {
			letters++
			if unicode.Is(unicode.Cyrillic, char) {
				cyrillic = true
			}
		}
	}
	return letters, cyrillic
}

func needsRussian(reply string) bool {
	letters, cyrillic := proseLetters(reply)
	return !cyrillic && letters > minLetters
}

func hasCyrillic(text string) bool {
	for _, char := range text {
		if unicode.Is(unicode.Cyrillic, char) {
			return true
		}
	}
	return false
}

type entry struct {
	Type             string `json:"type"`
	IsMeta           bool   `json:"isMeta"`
	IsSidechain      bool   `json:"isSidechain"`
	IsCompactSummary bool   `json:"isCompactSummary"`
	Message          struct {
		Content json.RawMessage `json:"content"`
	} `json:"message"`
}

// Text blocks of a message; ok is false when the content holds a tool result.
func textOf(content json.RawMessage) (text string, ok bool) {
	var plain string
	if json.Unmarshal(content, &plain) == nil {
		return plain, true
	}
	var blocks []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	if json.Unmarshal(content, &blocks) != nil {
		return "", false
	}
	var parts []string
	for _, block := range blocks {
		switch block.Type {
		case "tool_result":
			return "", false
		case "text":
			parts = append(parts, block.Text)
		}
	}
	return strings.Join(parts, "\n"), true
}

func userPrompt(text string) string {
	for _, pattern := range envelopes {
		text = pattern.ReplaceAllString(text, "")
	}
	return strings.TrimSpace(text)
}

// transcript returns the last real user prompt and the assistant text that follows
// the last user-role entry (tool results included), i.e. the final reply of the turn.
func transcript(path string) (prompt, reply string, ok bool) {
	file, err := os.Open(path)
	if err != nil {
		return "", "", false
	}
	defer file.Close()
	reader := bufio.NewReader(file)
	var final []string
	for {
		line, err := reader.ReadBytes('\n')
		if line = bytes.TrimSpace(line); len(line) > 0 {
			var item entry
			if json.Unmarshal(line, &item) == nil && !item.IsSidechain &&
				(item.Type == "user" || item.Type == "assistant") {
				text, plain := textOf(item.Message.Content)
				if item.Type == "assistant" {
					if plain && text != "" {
						final = append(final, text)
					}
				} else {
					final = nil
					if text = userPrompt(text); plain && !item.IsMeta && !item.IsCompactSummary && text != "" {
						prompt = text
					}
				}
			}
		}
		if err != nil {
			break
		}
	}
	return prompt, strings.Join(final, "\n"), prompt != ""
}

func run() int {
	raw, err := io.ReadAll(os.Stdin)
	if err != nil || !utf8.Valid(raw) {
		return 0
	}
	var payload map[string]json.RawMessage
	var event, path, last string
	var active bool
	if json.Unmarshal(raw, &payload) != nil ||
		json.Unmarshal(payload["hook_event_name"], &event) != nil || event != "Stop" {
		return 0
	}
	if payload["stop_hook_active"] != nil &&
		(json.Unmarshal(payload["stop_hook_active"], &active) != nil || active) {
		return 0
	}
	if json.Unmarshal(payload["transcript_path"], &path) != nil || path == "" {
		return 0
	}
	if payload["last_assistant_message"] != nil &&
		json.Unmarshal(payload["last_assistant_message"], &last) != nil {
		return 0
	}
	// Judge the reply before reading the transcript: long sessions have transcripts of tens of
	// megabytes, and most replies pass on their own.
	if last != "" && !needsRussian(last) {
		return 0
	}
	prompt, reply, ok := transcript(path)
	if !ok || !hasCyrillic(prompt) {
		return 0
	}
	if last != "" {
		reply = last
	}
	if !needsRussian(reply) {
		return 0
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetEscapeHTML(false)
	if encoder.Encode(map[string]string{"decision": "block", "reason": reason}) != nil {
		return 0
	}
	return 0
}

func main() {
	os.Exit(run())
}
