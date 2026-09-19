import sys

# ---------------------------
# Tokenizer
# ---------------------------
def tokenize(program: str):
    # Allowed keywords
    keywords = {"def", "conf", "env", "arg", "and", "or"}
    tokens = []
    i = 0
    while i < len(program):
        c = program[i]
        if c.isspace():
            i += 1
            continue
        elif c in "()":
            tokens.append(c)
            i += 1
        elif c in "!s":
            # "!" and "s" are one-character tokens.
            tokens.append(c)
            i += 1
        elif c.isalpha():
            # Read a (possibly multi-letter) token.
            start = i
            while i < len(program) and (program[i].isalnum() or program[i] == '_'):
                i += 1
            token = program[start:i]
            if token not in keywords:
                # Allow tokens that are not one of the reserved keywords.
                # (They will be treated as unexpected in our simple grammar.)
                # For safety, we could error here or simply pass.
                # In our design we expect only the allowed keywords.
                pass
            tokens.append(token)
        else:
            # Any other character is not allowed.
            raise SyntaxError(f"Invalid character '{c}' at position {i}")
    return tokens

# ---------------------------
# Parser
# ---------------------------
class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def current(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def consume(self, expected=None):
        if self.pos >= len(self.tokens):
            raise SyntaxError("Unexpected end of input")
        token = self.tokens[self.pos]
        if expected is not None and token != expected:
            raise SyntaxError(f"Expected '{expected}' but got '{token}'")
        self.pos += 1
        return token

    def parse_expr(self):
        token = self.current()
        if token is None:
            raise SyntaxError("Unexpected end of input in expression")
        # Handle the inversion operator "!"
        if token == "!":
            self.consume("!")
            operand = self.parse_expr()
            return ("not", operand)
        # Handle the "s" prefix (must be immediately followed by a source token)
        elif token == "s":
            self.consume("s")
            next_token = self.current()
            if next_token not in {"def", "conf", "env", "arg"}:
                raise SyntaxError(f"'s' must be immediately followed by a source token, got '{next_token}'")
            self.consume()  # consume the source token
            return ("source", next_token, True)
        # Handle grouping with parentheses
        elif token == "(":
            self.consume("(")
            # After '(' the next token must be an operator: "and" or "or"
            op = self.current()
            if op not in {"and", "or"}:
                raise SyntaxError(f"Expected 'and' or 'or' after '(', got '{op}'")
            self.consume()  # consume operator
            operands = []
            # Parse one or more expressions until we see a closing parenthesis.
            while self.current() != ")":
                operands.append(self.parse_expr())
                # (Extra tokens between expressions are allowed as separate tokens.)
            if self.current() != ")":
                raise SyntaxError("Missing closing parenthesis")
            self.consume(")")
            return (op, operands)
        # Handle a bare source token
        elif token in {"def", "conf", "env", "arg"}:
            self.consume()  # consume the source token
            return ("source", token, False)
        else:
            raise SyntaxError(f"Unexpected token: '{token}'")

# ---------------------------
# Evaluator
# ---------------------------
def eval_ast(node, attributes):
    """
    Recursively evaluates the AST node.
    The node is a tuple representing one of:
      ("source", source_name, requires_set)
      ("not", operand)
      ("and", [operands])
      ("or", [operands])
    """
    if type(node) is not tuple or len(node) < 2:
        raise ValueError("Invalid AST node format")
    node_type = node[0]
    if node_type == "source":
        source, requires_set = node[1], node[2]
        if source not in {"def", "conf", "env", "arg"}:
            raise ValueError(f"Unknown source: {source}")
        # For 'def', being defined implies the value is set.
        if source == "def":
            return "has_def" in attributes
        else:
            # For conf, env and arg, use has_conf_set (or has_env_set, has_arg_set) if requires_set is True.
            key = f"has_{source}_set" if requires_set else f"has_{source}"
            return key in attributes
    elif node_type == "not":
        operand = node[1]
        return not eval_ast(operand, attributes)
    elif node_type == "and":
        operands = node[1]
        # By convention: and with no operands returns True (vacuous truth)
        for op in operands:
            if not eval_ast(op, attributes):
                return False
        return True
    elif node_type == "or":
        operands = node[1]
        # By convention: or with no operands returns False
        if not operands:
            return False
        for op in operands:
            if eval_ast(op, attributes):
                return True
        return False
    else:
        raise ValueError(f"Unknown AST node type: {node_type}")

# ---------------------------
# The interpret Function
# ---------------------------
def interpret(attributes: set, program: str) -> bool:
    """
    Interprets the LI program string and evaluates it against the provided attributes.
    
    attributes: a set of strings; may contain any of:
       "has_def", "has_def_set", "has_conf", "has_conf_set",
       "has_env", "has_env_set", "has_arg", "has_arg_set"
       
    program: a string containing the LI program.
    
    Returns True if the LI program evaluates to True given the attributes,
    otherwise returns False.
    
    If there is a syntax or semantic error in the LI program, an error message is
    printed to stderr and the program exits with code 1.
    """
    try:
        tokens = tokenize(program)
    except Exception as e:
        sys.stderr.write(f"Tokenization error: {e}\n")
        sys.exit(1)
    if not tokens:
        sys.stderr.write("Empty LI program.\n")
        sys.exit(1)
    parser = Parser(tokens)
    try:
        ast = parser.parse_expr()
        if parser.pos != len(tokens):
            raise SyntaxError("Extra tokens after complete parsing")
    except Exception as e:
        sys.stderr.write(f"Syntax error: {e}\n")
        sys.exit(1)
    try:
        result = eval_ast(ast, attributes)
    except Exception as e:
        sys.stderr.write(f"Evaluation error: {e}\n")
        sys.exit(1)
    return result
