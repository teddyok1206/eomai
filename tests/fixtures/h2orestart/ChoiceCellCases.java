import soffice.HancomChoiceCellLayout;

public final class ChoiceCellCases {
    public static void main(String[] args) {
        System.out.print(HancomChoiceCellLayout.fitLeftMargin(args[0],
                Integer.parseInt(args[1]), Integer.parseInt(args[2]), Integer.parseInt(args[3]),
                Integer.parseInt(args[4]), Integer.parseInt(args[5])));
    }
}
