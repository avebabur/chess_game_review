import chess
import chess.pgn
import io

ECO_OPENINGS = {
    "B12": "Caro-Kann Defense",
    "B13": "Caro-Kann Defense: Exchange Variation",
    "B10": "Caro-Kann Defense",
    "B11": "Caro-Kann Defense: Two Knights Attack",
    "B14": "Caro-Kann Defense: Panov-Botvinnik Attack",
    "B15": "Caro-Kann Defense: Main Line",
    "B16": "Caro-Kann Defense: Bronstein-Larsen Variation",
    "B17": "Caro-Kann Defense: Steinitz Variation",
    "B18": "Caro-Kann Defense: Classical Variation",
    "B19": "Caro-Kann Defense: Classical, Spassky Variation",
    "A00": "Uncommon Opening",
    "A01": "Nimzowitsch-Larsen Attack",
    "A02": "Bird's Opening",
    "A04": "Reti Opening",
    "A05": "Reti Opening",
    "A06": "Reti Opening",
    "A10": "English Opening",
    "A13": "English Opening",
    "A20": "English Opening",
    "A30": "English Opening: Symmetrical",
    "A40": "Queen's Pawn Game",
    "A45": "Queen's Pawn Game",
    "A46": "Queen's Pawn Game",
    "A48": "King's Indian Defense",
    "A50": "Queen's Pawn Game",
    "A52": "Budapest Gambit",
    "A57": "Benko Gambit",
    "A80": "Dutch Defense",
    "B00": "Uncommon King's Pawn Opening",
    "B01": "Scandinavian Defense",
    "B02": "Alekhine's Defense",
    "B06": "Modern Defense",
    "B07": "Pirc Defense",
    "B20": "Sicilian Defense",
    "B21": "Sicilian Defense: Smith-Morra Gambit",
    "B22": "Sicilian Defense: Alapin Variation",
    "B23": "Sicilian Defense: Closed",
    "B27": "Sicilian Defense",
    "B30": "Sicilian Defense",
    "B32": "Sicilian Defense: Kalashnikov Variation",
    "B33": "Sicilian Defense: Sveshnikov Variation",
    "B40": "Sicilian Defense",
    "B44": "Sicilian Defense: Taimanov Variation",
    "B50": "Sicilian Defense",
    "B54": "Sicilian Defense",
    "B57": "Sicilian Defense: Classical, Anti-Nh3",
    "B60": "Sicilian Defense: Richter-Rauzer",
    "B70": "Sicilian Defense: Dragon Variation",
    "B80": "Sicilian Defense: Scheveningen Variation",
    "B90": "Sicilian Defense: Najdorf Variation",
    "C00": "French Defense",
    "C01": "French Defense: Exchange Variation",
    "C02": "French Defense: Advance Variation",
    "C03": "French Defense: Tarrasch Variation",
    "C10": "French Defense: Paulsen Variation",
    "C11": "French Defense: Classical",
    "C20": "King's Pawn Game",
    "C21": "Center Game",
    "C23": "Bishop's Opening",
    "C24": "Bishop's Opening: Berlin Defense",
    "C25": "Vienna Game",
    "C30": "King's Gambit",
    "C40": "King's Knight Opening",
    "C41": "Philidor Defense",
    "C42": "Petrov's Defense",
    "C44": "Scotch Game",
    "C45": "Scotch Game",
    "C46": "Three Knights Game",
    "C47": "Four Knights Game",
    "C50": "Italian Game",
    "C51": "Evans Gambit",
    "C52": "Evans Gambit",
    "C53": "Italian Game: Classical Variation",
    "C54": "Italian Game: Greco Attack",
    "C55": "Italian Game: Two Knights Defense",
    "C56": "Italian Game: Scotch Gambit",
    "C57": "Italian Game: Traxler Counterattack",
    "C60": "Ruy Lopez",
    "C61": "Ruy Lopez: Bird's Defense",
    "C62": "Ruy Lopez: Steinitz Defense",
    "C63": "Ruy Lopez: Schliemann Defense",
    "C64": "Ruy Lopez: Classical Defense",
    "C65": "Ruy Lopez: Berlin Defense",
    "C67": "Ruy Lopez: Berlin, Rio de Janeiro",
    "C68": "Ruy Lopez: Exchange Variation",
    "C70": "Ruy Lopez: Morphy Defense",
    "C78": "Ruy Lopez: Archangelsk",
    "C80": "Ruy Lopez: Open",
    "C84": "Ruy Lopez: Closed",
    "C88": "Ruy Lopez: Closed, Anti-Marshall",
    "C89": "Ruy Lopez: Marshall Attack",
    "C90": "Ruy Lopez: Closed",
    "D00": "Queen's Pawn Game",
    "D02": "Queen's Pawn Game: London System",
    "D04": "Queen's Pawn Game: Colle System",
    "D06": "Queen's Gambit",
    "D10": "Slav Defense",
    "D11": "Slav Defense",
    "D13": "Slav Defense: Exchange Variation",
    "D15": "Slav Defense",
    "D20": "Queen's Gambit Accepted",
    "D30": "Queen's Gambit Declined",
    "D31": "Queen's Gambit Declined",
    "D35": "Queen's Gambit Declined: Exchange Variation",
    "D37": "Queen's Gambit Declined: Classical",
    "D43": "Semi-Slav Defense",
    "D45": "Semi-Slav Defense: Meran Variation",
    "D50": "Queen's Gambit Declined",
    "D60": "Queen's Gambit Declined: Orthodox Defense",
    "D70": "Neo-Grunfeld Defense",
    "D80": "Grunfeld Defense",
    "D85": "Grunfeld Defense: Exchange Variation",
    "D90": "Grunfeld Defense",
    "E00": "Catalan Opening",
    "E04": "Catalan Opening: Open Defense",
    "E06": "Catalan Opening: Closed",
    "E10": "Queen's Pawn Game",
    "E12": "Queen's Indian Defense",
    "E15": "Queen's Indian Defense",
    "E20": "Nimzo-Indian Defense",
    "E21": "Nimzo-Indian Defense",
    "E32": "Nimzo-Indian Defense: Classical",
    "E40": "Nimzo-Indian Defense",
    "E50": "Nimzo-Indian Defense",
    "E60": "King's Indian Defense",
    "E61": "King's Indian Defense",
    "E62": "King's Indian Defense: Fianchetto Variation",
    "E70": "King's Indian Defense: Four Pawns Attack",
    "E73": "King's Indian Defense: Averbakh Variation",
    "E76": "King's Indian Defense: Four Pawns Attack",
    "E80": "King's Indian Defense: Samisch Variation",
    "E90": "King's Indian Defense: Classical",
    "E97": "King's Indian Defense: Mar del Plata",
}

BOOK_POSITIONS = set()

BOOK_LINES = [
    "1. e4 e5", "1. e4 c5", "1. e4 e6", "1. e4 c6", "1. e4 d5",
    "1. e4 g6", "1. e4 d6", "1. e4 Nf6",
    "1. d4 d5", "1. d4 Nf6", "1. d4 f5", "1. d4 e6", "1. d4 g6",
    "1. Nf3 d5", "1. Nf3 Nf6", "1. c4 e5", "1. c4 c5", "1. c4 Nf6",
    "1. e4 c6 2. d4 d5",
    "1. e4 c6 2. d4 d5 3. e5",
    "1. e4 c6 2. d4 d5 3. e5 Bf5",
    "1. e4 c6 2. d4 d5 3. Nc3",
    "1. e4 c6 2. d4 d5 3. exd5 cxd5",
    "1. e4 e5 2. Nf3 Nc6", "1. e4 e5 2. Nf3 Nc6 3. Bb5",
    "1. e4 e5 2. Nf3 Nc6 3. Bc4", "1. e4 e5 2. Nf3 Nc6 3. d4",
    "1. e4 e5 2. Nf3 Nf6",
    "1. e4 c5 2. Nf3 d6", "1. e4 c5 2. Nf3 Nc6", "1. e4 c5 2. Nf3 e6",
    "1. d4 d5 2. c4", "1. d4 d5 2. c4 e6", "1. d4 d5 2. c4 c6",
    "1. d4 d5 2. c4 dxc4",
    "1. d4 Nf6 2. c4 g6", "1. d4 Nf6 2. c4 e6",
    "1. d4 Nf6 2. c4 e6 3. Nc3 Bb4",
    "1. e4 e6 2. d4 d5",
    "1. e4 c6 2. d4 d5 3. e5 Bf5 4. Bd3 Bxd3 5. Qxd3 e6",
    "1. e4 c6 2. d4 d5 3. e5 Bf5 4. Nf3 e6",
]

def _build_book():
    for line in BOOK_LINES:
        import chess.pgn as pgn
        game = pgn.read_game(io.StringIO(line))
        if not game:
            continue
        board = game.board()
        BOOK_POSITIONS.add(board.fen().split(' ')[0])
        for move in game.mainline_moves():
            board.push(move)
            BOOK_POSITIONS.add(board.fen().split(' ')[0])

_build_book()


def is_book_move(board_fen):
    position = board_fen.split(' ')[0]
    return position in BOOK_POSITIONS


def get_opening_name(eco_code):
    if eco_code and eco_code in ECO_OPENINGS:
        return ECO_OPENINGS[eco_code]
    if eco_code:
        prefix = eco_code[:2]
        for code, name in ECO_OPENINGS.items():
            if code.startswith(prefix):
                return name
    return "Unknown Opening"


OPENING_PLANS = {
    "Scotch Game": (
        "White opens with e4 and quickly occupies the center with d4. "
        "Black should challenge the center with ...d5 or develop pieces before grabbing material."
    ),
    "Italian Game": (
        "Both sides develop toward the center. White targets f7 with Bc4 and Ng5 ideas; "
        "Black should castle early and contest the center with ...d5 or ...Na5."
    ),
    "Ruy Lopez": (
        "White pressures the e5 pawn with Bb5. Black's main plans are ...a6, ...b5, and solid development "
        "before opening the center."
    ),
    "Sicilian Defense": (
        "Black fights for the center from the flank with ...c5. White often builds a kingside attack; "
        "Black seeks counterplay on the queenside and open c-file."
    ),
    "French Defense": (
        "Black builds a solid pawn chain with ...e6 and ...d5. White tries to crack the center with e5 or f4; "
        "Black looks for ...c5 breaks."
    ),
    "Caro-Kann Defense": (
        "Black supports ...d5 with ...c6. White gets space; Black targets the white center with ...Bf5 or ...e6 setups."
    ),
    "Queen's Gambit": (
        "White offers the c-pawn to dominate the center. Black can accept or decline; "
        "piece development and central control decide the opening."
    ),
    "King's Indian Defense": (
        "Black allows White the center, then strikes with ...e5 or ...c5. "
        "White often plays on the queenside while Black attacks the king."
    ),
    "English Opening": (
        "White fianchettos and fights for flexible central control. "
        "Black should grab space with ...d5 or ...e5 when ready."
    ),
    "Scandinavian Defense": (
        "Black immediately challenges e4 with ...d5. White develops quickly; "
        "Black must develop pieces and not fall behind in tempo."
    ),
}


OPENING_IDEAS = [
    (
        "Caro-Kann Defense: Classical",
        "Classical Caro-Kann: White usually gets quicker development and kingside chances; Black wants exchanges, a solid king, and a timely ...c5 or ...e5 break before White's space turns into an attack.",
    ),
    (
        "Caro-Kann Defense: Two Knights",
        "Caro-Kann Two Knights: White develops quickly and pressures e5/f7; Black should hit the center before spending tempi on queen moves or flank pawn moves.",
    ),
    (
        "Caro-Kann Defense: Hillbilly",
        "Hillbilly Caro-Kann: Bc4 aims at f7, but after ...d5 Black gains tempo; White must prioritize development and castling over keeping the bishop active at all costs.",
    ),
    (
        "Caro-Kann Defense: Advance",
        "Advance Caro-Kann: White's e5 pawn gives space; Black's core plan is to undermine it with ...c5, trade light-square bishops when useful, and avoid passive piece placement.",
    ),
    (
        "Caro-Kann Defense",
        "Caro-Kann structure: Black accepts less space for solidity, then challenges White's center with ...c5 or ...e5; White needs development and king safety before launching pawn storms.",
    ),
    (
        "Ponziani Opening",
        "Ponziani: White builds a c3-d4 center, but the center becomes a target; Black should challenge it immediately with ...d5 or active piece pressure.",
    ),
    (
        "Hungarian Opening",
        "Hungarian-style setup: White delays the central break, so the strategic question is whether White can play d4/e4 under good conditions before Black equalizes space.",
    ),
    (
        "Horwitz Defense",
        "Horwitz Defense: Black keeps the structure flexible; White should claim space, while Black must choose a central break (...d5 or ...c5) instead of drifting.",
    ),
    (
        "French Defense",
        "French structure: the pawn chain defines the plans. White attacks on the kingside or center; Black must time ...c5 and ...f6 breaks to undermine e5.",
    ),
    (
        "Sicilian Defense",
        "Sicilian structure: White usually plays for central control and kingside initiative; Black looks for queenside and c-file counterplay, often with ...d5 as the equalizing break.",
    ),
    (
        "Italian Game",
        "Italian structure: development and king safety come first. The f7 pressure matters only if White can keep the center stable and avoid losing tempi.",
    ),
]


def get_opening_plan(opening_name):
    if not opening_name:
        return ""
    if opening_name in OPENING_PLANS:
        return OPENING_PLANS[opening_name]
    for key, plan in OPENING_PLANS.items():
        if key in opening_name:
            return plan
    return ""


def is_first_ply(half_move=None, side=None, move_number=None):
    """True only for White's first move (half_move 0). Black's reply is also
    move_number 1 in chess notation but must not repeat the opening idea."""
    if half_move is not None:
        try:
            return int(half_move) == 0
        except (TypeError, ValueError):
            return False
    return side == "White" and int(move_number or 0) == 1


def get_opening_idea(opening_name, move_number=None, half_move=None, side=None):
    """Curated strategic frame for the game's first ply only.

    Opening theory is useful once at the start; later moves should lead with
    board facts. Callers may pass ``half_move`` (preferred) or ``side`` +
    ``move_number`` as a fallback when half_move is unavailable.
    """
    if not opening_name or not is_first_ply(half_move, side, move_number):
        return ""
    for key, idea in OPENING_IDEAS:
        if key in opening_name:
            return idea
    return get_opening_plan(opening_name)


OPENING_TRAPS = {
    "Italian Game": {
        "premature_capture": (
            "In the Italian, grabbing pieces early (like Bxd5) lets Black equalize. "
            "Develop Bc4, O-O, and Re1 first."
        ),
        "no_castle": (
            "White needs to castle quickly in the Italian to avoid Ng4/Qh4 tricks targeting f2."
        ),
    },
    "Caro-Kann Defense": {
        "premature_capture": (
            "In the Caro-Kann, exchanging too early gives Black an easy game. Maintain tension."
        ),
        "no_castle": (
            "Castle before pushing forward. Black's light-squared bishop is active and can create threats."
        ),
    },
    "Sicilian Defense": {
        "premature_capture": (
            "In the Sicilian, White wants to build pressure, not trade pieces early."
        ),
        "no_castle": (
            "White must castle before launching a kingside attack in the Sicilian."
        ),
    },
    "Ruy Lopez": {
        "premature_capture": (
            "In the Ruy Lopez, Bxc6 is sometimes right but only with a concrete plan. "
            "Don't trade your bishop without a reason."
        ),
        "no_castle": (
            "The Ruy Lopez is a slow opening. Castle first, build pressure second."
        ),
    },
    "Scotch Game": {
        "premature_capture": (
            "In the Scotch, White has center control but needs to develop. "
            "Don't grab material at the cost of tempo."
        ),
        "no_castle": (
            "Both sides need to castle quickly in the Scotch. The center is open."
        ),
    },
    "French Defense": {
        "premature_capture": (
            "In the French, pawn tension is key. Don't resolve it prematurely without gaining something."
        ),
        "no_castle": (
            "Castle early in the French. The center can open suddenly with ...c5 or ...f6."
        ),
    },
    "Queen's Gambit": {
        "premature_capture": (
            "In the Queen's Gambit, maintain central tension. Don't trade without improving your position."
        ),
        "no_castle": (
            "Castle before expanding in the Queen's Gambit. The d-file can open fast."
        ),
    },
    "King's Indian Defense": {
        "premature_capture": (
            "In the King's Indian, don't trade away your attacking pieces too early. "
            "Black's plan is a kingside break."
        ),
        "no_castle": (
            "Castle kingside before pushing ...f5 or ...g5. An uncastled king gets overrun."
        ),
    },
    "English Opening": {
        "premature_capture": (
            "In the English, keep flexible structure. Premature exchanges help Black equalize."
        ),
        "no_castle": (
            "Get the king safe before opening the position. The fianchetto bishop needs a stable king."
        ),
    },
    "Scandinavian Defense": {
        "premature_capture": (
            "In the Scandinavian, Black must develop quickly after ...d5. Don't grab more without finishing development."
        ),
        "no_castle": (
            "Castle early in the Scandinavian. White develops with tempo after ...Qxd5."
        ),
    },
    "Petrov's Defense": {
        "premature_capture": (
            "In the Petrov, central tension matters more than material. Don't simplify without a plan."
        ),
        "no_castle": (
            "Castle before opening the center. Both sides have open e-files to worry about."
        ),
    },
    "London System": {
        "premature_capture": (
            "In the London, build your structure first. Early trades waste your setup time."
        ),
        "no_castle": (
            "Castle before pushing pawns forward. The Bf4/Bg5 setup needs king safety."
        ),
    },
    "Catalan Opening": {
        "premature_capture": (
            "In the Catalan, keep the long diagonal pressure. Don't trade your bishop without compensation."
        ),
        "no_castle": (
            "Castle before committing to queenside expansion. The center can open quickly."
        ),
    },
}


def get_opening_trap(opening_name, trap_key):
    if not opening_name or not trap_key:
        return ""
    traps = OPENING_TRAPS.get(opening_name)
    if traps:
        return traps.get(trap_key, "")
    for key, trap_dict in OPENING_TRAPS.items():
        if key in opening_name:
            return trap_dict.get(trap_key, "")
    return ""
