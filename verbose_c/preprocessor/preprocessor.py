import os
import re

class Preprocessor:
    """
    源代码预处理器，负责处理宏指令，如 #include 和 #define。
    """
    MAX_EXPANSION_DEPTH = 20  # 宏展开的最大深度
    
    def __init__(self):
        """
        初始化预处理器。
        """
        self.defines = {}
        self._included_files = set()

    def _expand_function_macro(self, line: str, macro_name: str, start_index: int) -> tuple[str, int]:
        """
        展开一个函数式宏
        
        TODO 进一步完善define的各种用法，以及条件宏
        """
        _, (arg_names, body) = self.defines[macro_name]
        
        # 寻找左括号
        i = start_index + len(macro_name)
        while i < len(line) and line[i].isspace():
            i += 1
        
        if i == len(line) or line[i] != '(':
            return line, start_index + len(macro_name)

        # 解析参数
        i += 1
        params_start = i
        paren_level = 1
        while i < len(line) and paren_level > 0:
            if line[i] == '(':
                paren_level += 1
            elif line[i] == ')':
                paren_level -= 1
            i += 1
        
        if paren_level != 0:
            # 括号不匹配
            return line, start_index + len(macro_name)
            
        params_end = i - 1
        params_str = line[params_start:params_end]
        
        # 分割参数
        actual_params = [p.strip() for p in params_str.split(',')]
        
        if len(actual_params) != len(arg_names):
            # 参数数量不匹配
            return line, i

        # 替换宏体
        expanded_body = body
        for arg_name, actual_param in zip(arg_names, actual_params):
            pattern = r'\b' + re.escape(arg_name) + r'\b'
            expanded_body = re.sub(pattern, actual_param, expanded_body)
            
        # 替换原始行
        new_line = line[:start_index] + expanded_body + line[i:]
        return new_line, start_index + len(expanded_body)

    def _apply_defines(self, line: str) -> str:
        """
        将已定义的宏应用于单行代码。
        """
        for _ in range(Preprocessor.MAX_EXPANSION_DEPTH):
            original_line = line
            i = 0
            while i < len(line):
                found_macro = False

                for name in sorted(self.defines.keys(), key=len, reverse=True):
                    if line.startswith(name, i):
                        is_function, content = self.defines[name]
                        if is_function:
                            line, i = self._expand_function_macro(line, name, i)
                        else:
                            line = line[:i] + content + line[i + len(name):]
                            i += len(content)
                        found_macro = True
                        break
                if not found_macro:
                    i += 1
            
            if line == original_line:
                break
        return line

    def _join_multiline_macros(self, source_code: str) -> str:
        """
        处理反斜杠，将代码拼接成一行
        """
        lines = source_code.splitlines()
        processed_code = ""
        i = 0
        while i < len(lines):
            line = lines[i]
            while line.endswith('\\') and i + 1 < len(lines):
                line = line[:-1] + lines[i + 1]
                i += 1
            processed_code += line + '\n'
            i += 1
        return processed_code

    def process(self, source_code: str, file_path: str) -> str:
        """
        处理源代码字符串，解析并展开宏定义，处理包含文件等。
        """
        abs_file_path = os.path.abspath(file_path)
        if abs_file_path in self._included_files:
            print(f"警告: 检测到循环包含 '{abs_file_path}'，已跳过。")
            return ""
        self._included_files.add(abs_file_path)

        source_code = self._join_multiline_macros(source_code)

        lines = source_code.splitlines()
        processed_lines = []
        
        include_pattern = re.compile(r'^\s*#include\s+(?:"([^"]+)"|<([^>]+)>)')
        define_pattern = re.compile(r'^\s*#define\s+([a-zA-Z_][a-zA-Z0-9_]*)(\([^\)]*\))?\s+(.*)')

        for line in lines:
            include_match = include_pattern.match(line)
            define_match = define_pattern.match(line)

            if include_match:
                # 处理 #include
                included_filename = include_match.group(1) or include_match.group(2)
                base_dir = os.path.dirname(file_path)
                path_to_include = os.path.join(base_dir, included_filename)

                if os.path.exists(path_to_include):
                    with open(path_to_include, 'r', encoding='utf-8') as f:
                        included_content = f.read()
                    
                    processed_content = self.process(included_content, path_to_include)
                    processed_lines.append(processed_content)
                else:
                    print(f"警告: #include 文件未找到 '{path_to_include}' (在 {file_path} 中)")
                    # processed_lines.append(line)
                    # 如果没有找到导入的目标文件，则直接丢弃掉这行宏代码

            elif define_match:
                # 处理 #define
                name = define_match.group(1)
                params_str = define_match.group(2)
                body = define_match.group(3).strip()
                
                if params_str:
                    # 函数宏
                    arg_list = [p.strip() for p in params_str.strip()[1:-1].split(',')]
                    self.defines[name] = (True, (arg_list, body))
                else:
                    # 普通宏
                    self.defines[name] = (False, body)
            else:
                # 普通代码行
                line = self._apply_defines(line)
                processed_lines.append(line)
        
        self._included_files.remove(abs_file_path)

        return "\n".join(processed_lines)
