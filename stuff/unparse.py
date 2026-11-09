"""Удаляет docstring'и и комментарии, пересобирает код через ast.unparse."""
import ast
import sys


class StripDocstrings(ast.NodeTransformer):
    def _strip(self, node):
        self.generic_visit(node)
        body = node.body
        if body and isinstance(body[0], ast.Expr):
            v = body[0].value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                node.body = body[1:] or [ast.Pass()]
        return node

    visit_Module = visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _strip


def main():
    if len(sys.argv) != 3:
        print("usage: python strip_src.py ИСХОДНИК РЕЗУЛЬТАТ")
        return 2
    src, dst = sys.argv[1], sys.argv[2]

    text = open(src, encoding="utf-8").read()
    tree = ast.parse(text)

    # 1) вырезаем docstring'и на уровне AST
    tree = StripDocstrings().visit(tree)
    ast.fix_missing_locations(tree)

    # 2) ast.unparse сам уберёт комментарии, лишние пробелы и пустые строки
    out = ast.unparse(tree) + "\n"

    # 3) проверка: AST должен совпасть с эталоном (исходник без docstring'ов)
    want = ast.dump(StripDocstrings().visit(ast.parse(text)))
    got = ast.dump(ast.parse(out))
    if got != want:
        print("strip: AST mismatch")
        return 1

    open(dst, "w", encoding="utf-8", newline="\n").write(out)
    print("strip: %d -> %d bytes" % (len(text.encode()), len(out.encode())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
