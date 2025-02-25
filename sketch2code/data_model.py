#!/usr/bin/python
# -*- coding: utf-8 -*-
import copy
import re
from pathlib import Path
from typing import *
from pyrsistent import PVector, pvector
from sketch2code.config import ROOT_DIR
from sketch2code.helpers import read_file


class Tag:
    # supported tags and its classes
    supported_tags = {}
    css_files = []
    stylesheets = [read_file(fpath) for fpath in css_files]

    def __init__(self, name: str, cls: List[str], children: List[Union['Tag', str]]):
        self.name = name
        self.cls = cls
        self.children = children

    @classmethod
    def deserialize(cls, o: dict):
        return cls(o['name'], o['class'], [cls.deserialize(v) if isinstance(v, dict) else v for v in o['children']])

    def serialize(self):
        return {
            "name": self.name,
            "class": self.cls,
            "children": [x if isinstance(x, str) else x.serialize() for x in self.children]
        }
    
    def is_equal(self, another: 'Tag'):
        return self.name == another.name \
               and self.cls == another.cls \
               and len(self.children) == len(another.children) \
               and all((c == ac if isinstance(c, str) else c.is_equal(ac) for c, ac in zip(self.children, another.children)))
            

    def clone(self) -> 'Tag':
        return self.__class__(self.name, copy.copy(self.cls),
                              [c if isinstance(c, str) else c.clone for c in self.children])

    def count_dsl_tokens(self):
        return 2 + len(self.cls) + sum([c.count_dsl_tokens() for c in self.children])

    def is_valid(self) -> bool:
        return self.name in self.supported_tags and all(c in self.supported_tags[self.name] for c in self.cls) and all(
            c.is_valid() if isinstance(c, Tag) else True for c in self.children)

    def linearize(self, tag: 'LinearizedTag' = None, replace_text: bool=False) -> 'LinearizedTag':
        if tag is None:
            tag = LinearizedTag.default()

        if self.name == 'html':
            for c in self.children:
                if isinstance(c, str):
                    tag.add_text('#text' if replace_text else c)
                else:
                    c.linearize(tag, replace_text)
            return tag

        tag.add_tag_and_class(self.name, tuple(self.cls))
        for c in self.children:
            if isinstance(c, str):
                tag.add_text('#text' if replace_text else c)
            else:
                c.linearize(tag, replace_text)
        tag.add_close_tag()
        return tag

    def to_body(self, join_char=""):
        children = join_char.join(x if isinstance(x, str) else x.to_body(join_char) for x in self.children)

        if self.name == "html":
            return children

        if len(self.cls) == 0:
            return f"<{self.name}>{children}</{self.name}>"
        return f"<{self.name} class=\"{' '.join(self.cls)}\">{children}</{self.name}>"

    def to_html(self, indent: int = 0, continuous_indent: int = 0, join_char=""):
        space = " " * continuous_indent
        children = join_char.join(
            x.to_html(indent, continuous_indent + indent, join_char) if isinstance(x, Tag) else space + (" " * indent) + x
            for x in self.children)

        if self.name == "html":
            # css_files = "\n".join([
            #     f'{space}{space}<link rel="stylesheet" href="{x.replace(str(ROOT_DIR), "http://localhost:8080")}" />'
            #     for x in self.css_files
            # ])
            stylesheets = join_char.join([f'<style>{x}</style>' for x in self.stylesheets])

            return f"""<html>
{space}<head>
{stylesheets}
{space}</head>
{space}<body>
{children}
{space}</body>
</html>
"""
        if len(self.cls) == 0:
            return f"""{space}<{self.name}>{join_char}{children}{join_char}{space}</{self.name}>"""
        return f"""{space}<{self.name} class=\"{' '.join(self.cls)}\">{join_char}{children}{join_char}{space}</{self.name}>"""


class LinearizedTag:

    tag_reg = re.compile(r'^<([a-z0-9]+)(?: class="([a-z0-9 -]*)")?>$')

    def __init__(self, str_tokens: PVector, tokens: PVector, opening_tags: List[int]):
        # List[str]
        self.str_tokens = str_tokens
        # List[Tuple[str, Tuple[str, ...]]]
        self.tokens = tokens
        self.opening_tags = opening_tags

    @staticmethod
    def default():
        return LinearizedTag(
            pvector([]),
            pvector([]),
            []
        )

    def clone(self):
        return LinearizedTag(self.str_tokens, self.tokens, copy.copy(self.opening_tags))
    
    def pop(self):
        if len(self.opening_tags) > 0 and self.opening_tags[-1] == len(self.tokens) - 1:
            self.opening_tags.pop()
        
        self.str_tokens = self.str_tokens.delete(len(self.str_tokens) - 1)
        self.tokens = self.tokens.delete(len(self.tokens) - 1)
        
    def add_open_tag(self, tag_name: str):
        self.opening_tags.append(len(self.tokens))
        token = f"<{tag_name}>"
        self.str_tokens = self.str_tokens.append(token)
        self.tokens = self.tokens.append((token, ()))

    def add_tag_and_class(self, tag_name: str, classes: Tuple[str, ...]):
        self.opening_tags.append(len(self.tokens))
        
        if len(classes) == 0:
            self.str_tokens = self.str_tokens.append(f'<{tag_name}>')
        else:
            self.str_tokens = self.str_tokens.append(f'<{tag_name} class="{" ".join(classes)}">')
        self.tokens = self.tokens.append((f"<{tag_name}>", classes))

    def add_close_tag(self) -> bool:
        if len(self.opening_tags) == 0:
            return False

        tag = self.tokens[self.opening_tags[-1]][0][1:-1]
        token = f"</{tag}>"
        self.str_tokens = self.str_tokens.append(token)
        self.tokens = self.tokens.append((token, ()))
        self.opening_tags.pop()
        return True

    def add_text(self, text: str):
        last_token_idx = len(self.tokens) - 1
        if len(self.opening_tags) > 0 and self.opening_tags[-1] != last_token_idx:
            # it means two things, either the last token is closing tag, or a text
            # we can just update it
            if self.str_tokens[-1].startswith("</"):
                self.str_tokens = self.str_tokens.append(text)
                self.tokens = self.tokens.append((text, ()))
            else:
                token = self.str_tokens[last_token_idx] + text
                self.str_tokens = self.str_tokens.set(last_token_idx, token)
                self.tokens = self.tokens.set(last_token_idx, (token, ()))
        else:
            self.str_tokens = self.str_tokens.append(text)
            self.tokens = self.tokens.append((text, ()))

    def add_class(self, tag_name: str, new_class: str) -> bool:
        """Add class to the most recent Tag"""
        if len(self.opening_tags) == 0:
            return False

        update_idx = self.opening_tags[-1]
        token, classes = self.tokens[update_idx]

        if token[1:-1] != tag_name:
            return False

        classes = (*classes, new_class)
        self.tokens = self.tokens.set(update_idx, (token, classes))
        self.str_tokens = self.str_tokens.set(update_idx, f'<{token[1:-1]} class="{" ".join(classes)}">')
        return True

    def is_valid(self):
        return len(self.opening_tags) == 0

    def can_add_close_tag(self) -> bool:
        return len(self.opening_tags) > 0

    def can_add_class(self, tag_name: str, new_class: str) -> bool:
        if len(self.opening_tags) > 0:
            token, classes = self.tokens[self.opening_tags[-1]]
            return token[1:-1] == tag_name and new_class not in classes

    def to_body(self, join_char=""):
        if len(self.opening_tags) > 0:
            closing_tokens = []
            for i in reversed(self.opening_tags):
                tag = self.tokens[i][0]
                closing_tokens.append(f'</{tag[1:-1]}>')
            return join_char.join(self.str_tokens) + join_char.join(closing_tokens)

        return join_char.join(self.str_tokens)


class Pix2CodeTag(Tag):
    supported_tags = {
        "html": set([]),
        "nav": set([]),
        "div": {"row", "col-12", "col-6", "col-3", "container-fluid", "grey-background"},
        "p": set([]),
        "h5": set([]),
        "button": {"btn", "btn-danger", "btn-warning", "btn-success", "btn-primary", "btn-secondary"},
    }
    css_files = [
        ROOT_DIR / "datasets/pix2code/css/main.css",
        ROOT_DIR / "datasets/pix2code/css/bootstrap.min.css",
    ]
    stylesheets = [read_file(fpath) for fpath in css_files]


class ToyTag(Tag):
    supported_tags = {
        "html": set([]),
        "div": {"row", "col-12", "col-6", "col-4", "col-3", "container-fluid", "grey-background"},
        "button": {"btn", "btn-danger", "btn-warning", "btn-success"},
    }
    css_files = [
        ROOT_DIR / "datasets/toy/css/main.css",
        ROOT_DIR / "datasets/toy/css/bootstrap.min.css",
    ]
    stylesheets = [read_file(fpath) for fpath in css_files]
