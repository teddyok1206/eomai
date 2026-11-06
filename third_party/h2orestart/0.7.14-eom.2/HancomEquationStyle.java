// SPDX-License-Identifier: GPL-3.0-or-later
package soffice;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Locale;
import java.util.regex.Pattern;

/** Translate Hancom style switches and isolated signs after structural conversion. */
public final class HancomEquationStyle {
    private static final int MAX_LENGTH = 65536;
    private static final int MAX_DEPTH = 128;
    private static final int MAX_CHARGE_LENGTH = 16;
    private static final Pattern CHARGE = Pattern.compile("[0-9]*[+-]");

    private HancomEquationStyle() { }

    public static String prepare(String source) {
        if (source == null || source.length() > MAX_LENGTH) {
            throw new IllegalArgumentException("equation script exceeds the supported bound");
        }
        String sign = isolatedSign(source);
        if (sign != null) {
            return "\"" + sign + "\"";
        }
        StringBuilder result = new StringBuilder(source.length() + 32);
        Deque<Integer> parentClosures = new ArrayDeque<Integer>();
        int closures = 0;
        boolean boundary = true;
        boolean quoted = false;
        boolean escaped = false;
        for (int cursor = 0; cursor < source.length();) {
            char character = source.charAt(cursor);
            if (quoted) {
                result.append(character);
                cursor++;
                if (character == '"' && !escaped) {
                    quoted = false;
                }
                escaped = character == '\\' && !escaped;
                continue;
            }
            if (character == '"') {
                quoted = true;
                escaped = false;
                result.append(character);
                cursor++;
                boundary = false;
                continue;
            }
            if (character == '^' || character == '_') {
                int next = cursor + 1;
                while (next < source.length() && Character.isWhitespace(source.charAt(next))) {
                    next++;
                }
                int end = next;
                if (next < source.length() && source.charAt(next) == '{') {
                    end++;
                    while (end < source.length() && end - next <= MAX_CHARGE_LENGTH
                            && source.charAt(end) != '}') {
                        end++;
                    }
                    if (end < source.length() && source.charAt(end) == '}') {
                        String charge = source.substring(next + 1, end).trim();
                        if (CHARGE.matcher(charge).matches()) {
                            result.append(character).append("{\"")
                                    .append(charge.replace('-', '\u2212')).append("\"}");
                            cursor = end + 1;
                            boundary = true;
                            continue;
                        }
                    }
                } else if (next < source.length()
                        && (source.charAt(next) == '+' || source.charAt(next) == '-')) {
                    int following = next + 1;
                    if (following == source.length() || Character.isWhitespace(source.charAt(following))
                            || source.charAt(following) == '}' || source.charAt(following) == ')') {
                        result.append(character).append("{\"")
                                .append(source.charAt(next) == '-' ? '\u2212' : '+').append("\"}");
                        cursor = following;
                        boundary = true;
                        continue;
                    }
                }
            }
            if (character == '{') {
                if (parentClosures.size() >= MAX_DEPTH) {
                    throw new IllegalArgumentException("equation nesting exceeds the supported bound");
                }
                parentClosures.push(closures);
                closures = 0;
                result.append(character);
                cursor++;
                boundary = true;
                continue;
            }
            if (character == '}') {
                if (parentClosures.isEmpty()) {
                    throw new IllegalArgumentException("equation has an unmatched closing group");
                }
                closeStyles(result, closures);
                closures = parentClosures.pop();
                result.append(character);
                cursor++;
                boundary = true;
                continue;
            }
            String style = boundary ? styleAt(source, cursor) : null;
            if (style != null) {
                result.append(style.equals("it") ? "italic { " : "nitalic { ");
                closures++;
                if (style.equals("rmbold")) {
                    result.append("bold { ");
                    closures++;
                }
                if (closures > MAX_DEPTH) {
                    throw new IllegalArgumentException("equation style switches exceed the supported bound");
                }
                cursor += style.length();
                // Hancom accepts compact and repeated switches such as rmA and rm rmX.
                boundary = true;
                continue;
            }
            result.append(character);
            cursor++;
            boundary = !Character.isLetterOrDigit(character) && character != '_';
        }
        if (quoted || !parentClosures.isEmpty()) {
            throw new IllegalArgumentException("equation has an unterminated quote or group");
        }
        closeStyles(result, closures);
        return result.toString();
    }

    private static String styleAt(String source, int cursor) {
        if (source.regionMatches(true, cursor, "rmbold", 0, 6)) {
            return "rmbold";
        }
        if (source.regionMatches(true, cursor, "rm", 0, 2)) {
            return "rm";
        }
        if (source.regionMatches(true, cursor, "it", 0, 2)) {
            int next = cursor + 2;
            // Do not interpret ordinary multi-letter identifiers such as item as switches.
            if (next == source.length() || !Character.isLowerCase(source.charAt(next))
                    || next + 1 == source.length()
                    || !Character.isLetter(source.charAt(next + 1))) {
                return "it";
            }
        }
        return null;
    }

    private static void closeStyles(StringBuilder result, int closures) {
        for (int index = 0; index < closures; index++) {
            result.append(" }");
        }
    }

    private static String isolatedSign(String source) {
        String candidate = source.trim();
        for (int index = 0; index < MAX_DEPTH; index++) {
            if (candidate.startsWith("{") && candidate.endsWith("}")) {
                candidate = candidate.substring(1, candidate.length() - 1).trim();
                continue;
            }
            String style = styleAt(candidate, 0);
            if (style == null) {
                break;
            }
            candidate = candidate.substring(style.length()).trim();
        }
        switch (candidate.toUpperCase(Locale.ROOT)) {
            case "-": return "\u2212";
            case "+": return "+";
            case "=": return "=";
            case "TIMES": return "\u00d7";
            case "CDOT": return "\u22c5";
            case "DIVIDE": return "\u00f7";
            case "PLUSMINUS": return "\u00b1";
            case "MINUSPLUS": return "\u2213";
            default: return null;
        }
    }
}
