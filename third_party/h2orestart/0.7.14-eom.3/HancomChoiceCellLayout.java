// SPDX-License-Identifier: GPL-3.0-or-later
package soffice;

/** Fit a standalone choice label inside its existing cell, not into its neighbour. */
public final class HancomChoiceCellLayout {
    private HancomChoiceCellLayout() { }

    public static int fitLeftMargin(String text, int cellWidth, int fontHeight,
            int marginLeft, int marginRight, int indent) {
        if (text == null || text.length() > 64 || cellWidth <= 0 || fontHeight <= 0
                || marginLeft <= 0 || marginRight < 0 || indent != 0) {
            return marginLeft;
        }
        String label = text.trim();
        if (label.length() != 1 || label.charAt(0) < '\u2460' || label.charAt(0) > '\u2464') {
            return marginLeft;
        }
        // HWP paragraph margins have twice the resolution of cell/font units.
        // Reserve one font em conservatively; never widen or move the cell.
        long available = Math.max(0L, 2L * (cellWidth - (long) fontHeight) - marginRight);
        return (int) Math.min(marginLeft, available);
    }
}
