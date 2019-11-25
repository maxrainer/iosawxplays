#!/usr/bin/python

ANSIBLE_METADATA = {
    "metadata_version": "1.1",
    "status": ["preview"],
    "supported by": "community"
}

DOCUMENTATION = '''
---
module: config_compliance

short_description: Check if parts of a config (based on search criteria) are equal to a certain template.

version_added: "2.6.1"

description:
    - "TODO long description"
    
options:
    source:
        description: 
            - The absolute path to the config file, which should be checked.
        required: True
        type: str
    
    destination_expected:
        description: 
            - The absolute path to I(destination_expected). This file contains the remaining parts of the template which were not found in the extract part of the config.
              For example: The run compares the extracted lines A, B and C (extracted from the input config based on the search criteria) and the template lines A, B, C and D. 
              After the run the I(destination_expected) file will contain line D, since it was in the template but not in the extracted part of the config.
        required: True
        type: str
      
    destination_not_expected:
        description: 
            - The absolute path to I(destination_not_expected). This file contains the remaining parts of the extracted config which were not found in the template.
              For example: The run compares the extracted lines A, B, C, D and E (extracted from the input config based on the search criteria) and the template lines A, B and D. 
              After the run the I(destination_not_expected) file will contain the lines C and E, since they were in the extracted part of the config but not in the template.
        required: True
        type: str
      
    template:
        description: 
            - The absolute path to the template file, which will be used for the comparison.
        required: True
        type: str
      
    template_args:
        description: 
            - A dictionary of the arguments for the template. This parameter is optional because template can have no variables at all.
              For example: The following template line: "hostname {{ hostname }}". The dictionary should then have an entry with the key "hostname" and a value -> hostname: myHostname
        required: False
        default: {}
        type: dict       
    
    search_mode:
        description: 
            - Indicates how the I(search_start) will be used to extract parts of the config.
              "line": searches for single lines starting with I(search_start) while ignoring blocks.
              "block": searches for a block start matching the I(search_start) while ignoring single lines.
              "block_lines": searches for single lines and block starts starting with I(search_start).
              "global": Just compares the lines in the given I(template) with the global config.
        required: True
        choices: 
            - line
            - block
            - block_lines
            - global
      
    search_start:
        description: 
            - The value which will be used to extract parts of the config. Required when I(search_mode=line|block|block_lines)
              If the search mode is "line" or "block_lines" this value can be a regex.
              If the search mode is "block" the value must be identical to the start of the block.
              If the search mode is "global" this value is not used.
        required: False
        type: str
        
    search_end:
        description: 
            - This value is only used if I(search_mode) is "block" and then it is still optional.
        required: False
        type: str
      
    compare_method:
        description: 
            - Dictates how each entry (config with template) should be compared.
        required: True
        choices:
            - equals
        
    compare_args:
        description: 
            - Additional parameter to control how and what will be compared. 
              keep_block_start: Indicates that the start of the found block should be kept and be used for comparison.
              keep_block_end: Indicates that the end of the found block should be kept and be used for comparison.
              strict_order: Indicates that the order of the lines is crucial.
        required: False
        choices:
            - keep_block_start
            - keep_block_end
            - strict_order
      
    ignore_lines:
        description: 
            - Only used if search mode is "block" and then it still can be empty. 
              The lines given through this parameter will be ignored during comparison.
        required: False
        type: list
      
    log_description:
        description: 
            - If a value is set it will be used to add a "header" in the expected and not_expected files to make it easier to mark which lines were generated in which run.
        required: False
        type: str
    
author:
    - Philipp Wanko 
'''

EXAMPLES = '''

# Extracting access interfaces    
- name: interface access 
  config_compliance:
    source: "files/tmp/startupConfig.txt"
    destination_expected: "files/results/expected_startupConfig.txt"
    destination_not_expected: "files/results/not_expected_startupConfig.txt"
    template: templates/interface/access_r1.j2
    search_mode: "block"
    search_start: "interface FastEthernet1/0/2"
    search_end: "!"
    ignore_lines:
      - "switchport access vlan [0-9]+" 
      - "switchport voice vlan [0-9]+"
      - "description .*"
    compare_method: "equals"
    log_description: "interface access FastEthernet 1/0/2"
    compare_args: []
  
# Extracting aaa lines  
- name: check template for aaa
  config_compliance:
    source: "files/tmp/startupConfig.txt"
    destination_expected: "files/results/expected_startupConfig.txt"
    destination_not_expected: "files/results/not_expected_startupConfig.txt"
    template: templates/aaa.j2
    template_args: { }
    search_mode: "line"
    search_start: aaa
    search_end: "!"
    compare_method: "equals"
    compare_args: ["strict_order"]
    log_description: AAA Block
'''

RETURN = '''
expected_changed:
    description: True if one or more template lines were not matched, False otherwise.
    returned: changed
    type: bool
    
expected:
    description: If expected_changed is True this value will contain all remaining template lines.
    returned: changed and if expected_changed=True
    type: list
    sample: ["no ip http server", "logging history size 500"]
    
not_expected_changed:
    description: True if one or more config lines were not matched, False otherwise.
    returned: changed
    type: bool

not_expected:
    description: If not_expected_changed is True this value will contain all remaining config lines.
    returned: changed and if not_expected_changed=True
    type: list
    sample: ["no ip http server", "logging history size 500"]
    
not_expected_commands:
    description: If not_expected_changed is True this value will contain all commands to remove those not expected config parts.
    returned: changed and if not_expected_changed=True
    type: list

expected_commands:
    description: If expected_changed is True this value will contain all commands to add the lines missing in the config.
    returned: changed and if expected_changed=True
    type: list
    sample: ["access-list 5 permit any log"]

all_commands:
    description: Contains all commands so that the config will match the configured template.
    returned: always
    type: list
    sample: ["access-list 5 permit any log", "access-list 10 permit any log", "access-list 47 permit 138.205.137.15", "access-list 90 permit 138.205.138.69"]
'''

import os
import re
import sys

import jinja2
from ansible.module_utils.basic import AnsibleModule
from jinja2.exceptions import TemplateError

__COMPARE_ARG_KEEP_START = "keep_block_start"
__COMPARE_ARG_KEEP_END = "keep_block_end"
__COMPARE_ARG_STRICT = "strict_order"

__COMPARE_METHOD_EQUALS = "equals"

__SEARCH_MODE_LINE = "line"
__SEARCH_MODE_BLOCK = "block"
__SEARCH_MODE_BLOCK_LINES = "block_lines"
__SEARCH_MODE_GLOBAL = "global"

__VALID_COMPARE_METHODS = [__COMPARE_METHOD_EQUALS]
__VALID_COMPARE_ARGS = [__COMPARE_ARG_KEEP_START, __COMPARE_ARG_KEEP_END, __COMPARE_ARG_STRICT]
__VALID_SEARCH_MODES = [__SEARCH_MODE_LINE, __SEARCH_MODE_BLOCK, __SEARCH_MODE_BLOCK_LINES, __SEARCH_MODE_GLOBAL]

__LINE_DELIMITER = "@!!@"

__NOT_WHITESPACE_START_REGEX = re.compile("^[^\s]")
__WHITESPACE_START_REGEX = re.compile("^\s")
__IS_BLOCK_LINE_REGEX = re.compile("^\s")
__REMOVE_DELIMITER = re.compile(".*" + __LINE_DELIMITER)

__EDIT_DISTANCE_THRESHOLD = 6


class Template:

    def __init__(self, name, content):
        self.name = name
        self.content = content

    def get_content(self):
        return self.content


class Block:

    def __init__(self, start, end=None, content=None):
        self.start = start
        self.end = end

        if content is None:
            self.content = []
        else:
            self.content = content

    def get_start(self):
        return self.start

    def get_end(self):
        return self.end

    def set_end(self, end):
        if end:
            self.end = end

    def add_content_line(self, line, strip=True):
        if line:
            if strip:
                line = line.strip()

            self.content.append(line)

    def get_content(self, add_start=False, add_end=False):
        block_content = self.content

        if add_start:
            block_content = [self.start] + block_content

        if add_end and self.end:
            block_content = block_content + [self.end]

        return block_content


def run_module(module):
    module_result = dict(changed=False, failed=False, msg="", expected_changed=False, expected=[],
                         not_expected_changed=False, not_expected=[], not_expected_commands=[], expected_commands=[],
                         all_commands=[])

    error = validate_input(module)

    if error:
        module_result["msg"] = error
        module.fail_json(**module_result)

        return

    config_path = module.params["source"]
    result_path_expected = module.params["destination_expected"]
    result_path_not_expected = module.params["destination_not_expected"]
    template_path = module.params["template"]
    template_args = module.params["template_args"]
    search_mode = module.params["search_mode"]
    search_start = module.params["search_start"]
    search_end = module.params["search_end"]
    compare_method = module.params["compare_method"]
    compare_args = module.params["compare_args"]
    ignore_lines = module.params["ignore_lines"]
    log_description = module.params["log_description"]
    file_output = module.params["file_output"]
    changed_if = module.params["changed_if"]

    try:
        if "\n" in config_path or "\r\n" in config_path:
            # we assume that we either get a valid path or the config as a single string. If the string contains an
            # invalid path the config_lines will contain utter garbage.
            config_lines = config_path.splitlines()
        else:
            config_lines = load_config(config_path)

    except (OSError, IOError) as e:
        module_result["msg"] = "Exception while loading config file -> {}:{}".format(type(e).__name__, str(e))
        module.fail_json(**module_result)

        return

    try:
        template = create_template(template_path, template_args)
    except (UnboundLocalError, TemplateError) as e:
        module_result["msg"] = "Exception while rendering template -> {}:{}".format(type(e).__name__, str(e))
        module.fail_json(**module_result)

        return

    try:
        if __SEARCH_MODE_LINE == search_mode:
            lines, remaining_config = extract_lines(config_lines, search_start, search_end)
            too_much, missing = compare_lines(template, lines, compare_method, compare_args)

        elif __SEARCH_MODE_BLOCK == search_mode:
            block, remaining_config = extract_block(config_lines, search_start, search_end)
            too_much, missing = compare_block(template, block, compare_method, compare_args, ignore_lines)

        elif __SEARCH_MODE_BLOCK_LINES == search_mode:
            lines, remaining_config = extract_block_lines(config_lines, search_start, search_end)
            too_much, missing = compare_lines(template, lines, compare_method, compare_args)

        elif __SEARCH_MODE_GLOBAL == search_mode:

            too_much, missing, remaining_config = check_global(config_lines, template, compare_method, compare_args)

        else:
            module_result["msg"] = "Search mode {} not supported".format(search_mode)
            module.fail_json(**module_result)

            return

        if file_output:
            write_results(result_path_expected, result_path_not_expected, log_description, too_much, missing)
            write_remaining_config(config_path, remaining_config)

        if too_much:
            module_result["not_expected_changed"] = True
            module_result["not_expected"] = too_much

            if changed_if == "both" or changed_if == "not_expected":
                module_result["changed"] = True

            not_expected_commands = []
            parsed_too_much = map(lambda x: __REMOVE_DELIMITER.sub("", x), too_much)

            for line in parsed_too_much:
                if line:
                    if not line.startswith("no "):
                        line = "no " + line
                        not_expected_commands.append(line)
                    else:
                        not_expected_commands.append(line)

            module_result["not_expected_commands"] = not_expected_commands

        if missing:
            module_result["expected_changed"] = True
            module_result["expected"] = missing

            if changed_if == "both" or changed_if == "expected":
                module_result["changed"] = True

            expected_commands = map(lambda x: __REMOVE_DELIMITER.sub("", x), missing)
            module_result["expected_commands"] = expected_commands

        module_result["all_commands"] = template.get_content()

        module_result["msg"] = "Success"
        module.exit_json(**module_result)
    except Exception as e:
        _, _, exc_tb = sys.exc_info()

        module_result["msg"] = "Exception during compare -> {}:{}  (in line: {}".format(type(e).__name__, str(e),
                                                                                        exc_tb.tb_lineno)
        module.fail_json(**module_result)


def validate_input(module):
    if not module.params["source"]:
        return "source is empty, provide a valid source"

    if not module.params["destination_expected"]:
        return "destination_expected is empty, provide a valid destination_expected"

    if not module.params["destination_not_expected"]:
        return "destination_not_expected is empty, provide a valid destination_not_expected"

    if not module.params["template"]:
        return "template is empty, provide a valid template"

    error = validate_compare_method(module)

    if error:
        return error

    error = validate_search_mode(module)

    if error:
        return error

    error = validate_compare_args(module)

    if error:
        return error

    if module.params["search_end"] is None:
        module.params["search_end"] = ""

    if module.params["template_args"] is None:
        module.params["template_args"] = {}

    if module.params["ignore_lines"] is None:
        module.params["ignore_lines"] = []

    return ""


def validate_compare_method(module):
    if not module.params["compare_method"]:
        return "compare_method is empty, provide a valid compare_method"
    else:
        module.params["compare_method"] = str.lower(module.params["compare_method"])
        compare_method = module.params["compare_method"]

        if compare_method not in __VALID_COMPARE_METHODS:
            return "{} is not supported as compare method, valid methods are {}".format(",".join(compare_method),
                                                                                        ",".join(
                                                                                            __VALID_COMPARE_METHODS))

    return ""


def validate_search_mode(module):
    if not module.params["search_mode"]:
        return "search_mode is empty, provide a valid search_mode"
    else:
        module.params["search_mode"] = str.lower(module.params["search_mode"])
        search_mode = module.params["search_mode"]
        search_start = module.params["search_start"] if module.params["search_start"] else ""

        if search_mode not in __VALID_SEARCH_MODES:
            return "{} is not supported as search mode, valid modes are {}".format(",".join(search_mode),
                                                                                   ",".join(__VALID_SEARCH_MODES))

        if search_mode != __SEARCH_MODE_GLOBAL and not search_start:
            return "search_start is empty, you must provide a search_start for the modes: line, block and block_lines"

    return ""


def validate_compare_args(module):
    if module.params["compare_args"] is None:
        module.params["compare_args"] = []
    else:
        module.params["compare_args"] = map(str.lower, module.params["compare_args"])
        compare_args = module.params["compare_args"]
        invalid_args = []

        for arg in compare_args:
            if arg not in __VALID_COMPARE_ARGS:
                invalid_args.append(arg)

        if invalid_args:
            return "{} are not supported as compare arguments, valid arguments are {}".format(",".join(invalid_args),
                                                                                              ",".join(
                                                                                                  __VALID_COMPARE_ARGS))

    return ""


def compare_block(template, block, compare_method, compare_args, ignore_lines):
    if __COMPARE_METHOD_EQUALS == compare_method:
        return block_check_equal(block, template, compare_args, ignore_lines)

    return [], []


def block_check_equal(block, template, compare_args, ignore_lines):
    if not block.get_content():
        template_lines = template.get_content()

        for i, _ in enumerate(template_lines):
            template_lines[i] = "{}{}{}".format(block.get_start(), __LINE_DELIMITER, template_lines[i])

        return [], template_lines

    add_block_start = __COMPARE_ARG_KEEP_START in compare_args
    add_block_end = __COMPARE_ARG_KEEP_END in compare_args

    block_lines = block.get_content(add_block_start, add_block_end)
    template_lines = template.get_content()

    strict_mode = __COMPARE_ARG_STRICT in compare_args

    if is_hash_equal(block_lines, template_lines, strict_mode):
        return [], []

    block_lines, template_lines = filter_ignore_lines(block_lines, template_lines, ignore_lines)

    if strict_mode:
        remaining_block_lines, remaining_template_lines = block_strict_check(block_lines, template_lines)
    else:
        remaining_block_lines, remaining_template_lines = block_normal_check(block_lines, template_lines)

    block_start = block.get_start()

    for i, _ in enumerate(remaining_block_lines):
        remaining_block_lines[i] = "{}{}{}".format(block_start, __LINE_DELIMITER, remaining_block_lines[i])

    for i, _ in enumerate(remaining_template_lines):
        remaining_template_lines[i] = "{}{}{}".format(block_start, __LINE_DELIMITER, remaining_template_lines[i])

    return remaining_block_lines, remaining_template_lines


def block_strict_check(block_lines, template_lines):
    remaining_block_lines = list(block_lines)
    remaining_template_lines = list(template_lines)

    if len(block_lines) == len(template_lines):
        for i in range(0, len(block_lines)):
            block_line = block_lines[i]
            template_line = template_lines[i]

            if block_line == template_line:
                remaining_block_lines.remove(block_line)
                remaining_template_lines.remove(block_line)

            else:
                diff = levenshtein(block_line, template_line)

                if diff > __EDIT_DISTANCE_THRESHOLD:
                    remaining_block_lines = list(block_lines)
                    remaining_template_lines = list(template_lines)
                    break

    return remaining_block_lines, remaining_template_lines


def block_normal_check(block_lines, template_lines):
    remaining_block_lines = list(block_lines)
    remaining_template_lines = list(template_lines)

    for block_line in block_lines:
        if block_line in template_lines:
            remaining_block_lines.remove(block_line)
            remaining_template_lines.remove(block_line)

    return remaining_block_lines, remaining_template_lines


def is_hash_equal(block_lines, template_lines, strict_order):
    if not strict_order:
        block_lines = sorted(block_lines)
        template_lines = sorted(template_lines)

    block_data = "".join(block_lines)
    template_data = "".join(template_lines)

    block_hash = hash(block_data)
    template_hash = hash(template_data)

    return block_hash == template_hash


def filter_ignore_lines(block_lines, template_lines, ignore_lines):
    filtered_block_lines = []
    filtered_template_lines = []

    for ignore_line in ignore_lines:
        r = re.compile(ignore_line)

        filtered_block_lines.extend(filter(r.search, block_lines))
        filtered_template_lines.extend(filter(r.search, template_lines))

    block_lines = [x for x in block_lines if x not in filtered_block_lines]
    template_lines = [x for x in template_lines if x not in filtered_template_lines]

    return block_lines, template_lines


def levenshtein(s, t):
    if s == t:
        return 0
    elif s is None or len(s) == 0:
        return len(t)
    elif t is None or len(t) == 0:
        return len(s)

    d = [[0 for _ in range(len(t))] for _ in range(len(s))]

    for i in range(1, len(s)):
        d[i][0] = i

    for j in range(1, len(t)):
        d[0][j] = j

    for j in range(1, len(t)):
        for i in range(1, len(s)):
            cost = 0 if s[i] == t[j] else 1

            d[i][j] = min(d[i - 1][j] + 1,
                          d[i][j - 1] + 1,
                          d[i - 1][j - 1] + cost)

    return d[len(s) - 1][len(t) - 1]


def extract_block(config_lines, search_start, search_end):
    block = Block(search_start)

    try:
        start_index = config_lines.index(search_start)
    except ValueError:
        return block, config_lines

    delete_indices = [start_index]
    index = start_index + 1

    while index < len(config_lines) and not is_end_of_block(config_lines[index], search_end):
        block.add_content_line(config_lines[index])
        delete_indices.append(index)

        index += 1

    if config_lines[index] == search_end:
        block.set_end(search_end)
        delete_indices.append(index)

    delete_indices = reversed(sorted(delete_indices))

    for index in delete_indices:
        del config_lines[index]

    return block, config_lines


def is_end_of_block(line, search_end):
    if not search_end:
        return not __IS_BLOCK_LINE_REGEX.match(line)

    end_regex = re.compile(search_end)

    return not __IS_BLOCK_LINE_REGEX.match(line) or end_regex.match(line)


def compare_lines(template, lines, compare_method, compare_args):
    if __COMPARE_METHOD_EQUALS == compare_method:
        return line_check_equal(lines, template, compare_args)

    return [], []


def line_check_equal(lines, template, compare_args):
    template_lines = template.get_content()
    strict_mode = __COMPARE_ARG_STRICT in compare_args

    if strict_mode:
        remaining_lines, remaining_template_lines = line_strict_check(lines, template_lines)
    else:
        remaining_lines, remaining_template_lines = line_normal_check(lines, template_lines)

    return remaining_lines, remaining_template_lines


def line_strict_check(lines, template_lines):
    remaining_lines = list(lines)
    remaining_template_lines = list(template_lines)

    if len(lines) == len(template_lines):
        for i in range(0, len(lines)):
            line = lines[i]
            template_line = template_lines[i]

            if line == template_line:
                remaining_lines.remove(line)
                remaining_template_lines.remove(line)

            else:
                diff = levenshtein(line, template_line)

                if diff > __EDIT_DISTANCE_THRESHOLD:
                    remaining_lines = list(lines)
                    remaining_template_lines = list(template_lines)
                    break

    return remaining_lines, remaining_template_lines


def line_normal_check(lines, template_lines):
    remaining_lines = list(lines)
    remaining_template_lines = list(template_lines)

    for line in lines:
        if line in template_lines:
            remaining_lines.remove(line)
            remaining_template_lines.remove(line)

    return remaining_lines, remaining_template_lines


def extract_lines(config_lines, search_start, search_end):
    found_lines = []
    delete_indices = []

    start_regex = re.compile(search_start)

    for i, line in enumerate(config_lines):
        block_start = is_block_start(config_lines[i], config_lines[i + 1] if (i + 1) < len(config_lines) else None)

        if start_regex.match(line) and not block_start:
            line = line.strip()

            found_lines.append(line)
            delete_indices.append(i)

            if line.endswith("@"):
                extra_indexes, extra_lines = extract_additional_lines(config_lines, i + 1, "@")

                found_lines += extra_lines
                delete_indices += extra_indexes

    delete_indices = reversed(sorted(delete_indices))

    for index in delete_indices:
        del config_lines[index]

    return found_lines, config_lines


def extract_block_lines(config_lines, search_start, search_end):
    found_lines = []
    delete_indices = []

    start_regex = re.compile(search_start)

    for i, line in enumerate(config_lines):
        if start_regex.match(line):
            line = line.strip()

            found_lines.append(line)
            delete_indices.append(i)

            if line.endswith("@"):
                extra_indexes, extra_lines = extract_additional_lines(config_lines, i + 1, "@")

                found_lines += extra_lines
                delete_indices += extra_indexes

            else:
                last_line = (i + 1) >= len(config_lines)

                if not last_line:
                    next_line = config_lines[i + 1]

                    if next_line.startswith(" "):
                        extra_indexes, extra_lines = extract_additional_lines2(config_lines, i + 1, " ")

                        found_lines += extra_lines
                        delete_indices += extra_indexes

    delete_indices = reversed(sorted(delete_indices))

    for index in delete_indices:
        del config_lines[index]

    return found_lines, config_lines


def is_block_start(current_line, next_line):
    if not current_line or not next_line:
        return False

    current_match = __NOT_WHITESPACE_START_REGEX.match(current_line)
    next_match = __WHITESPACE_START_REGEX.match(next_line)

    if current_match and next_match:
        return True

    return False


def extract_additional_lines(config_lines, start_index, search_until):
    extra_lines = []
    extra_indices = []

    for i, line in enumerate(config_lines[start_index:]):
        line = line.strip()

        if line.endswith(search_until):
            extra_lines.append(line)
            extra_indices.append(i + start_index)
            break

        else:
            extra_lines.append(line)
            extra_indices.append(i + start_index)

    return extra_indices, extra_lines


def extract_additional_lines2(config_lines, start_index, search_until):
    extra_lines = []
    extra_indices = []

    for i, line in enumerate(config_lines[start_index:]):
        if not line.startswith(search_until):
            line = line.strip()
            # keep this special case in mind -> where after a line block a new line block starts immediately (without ! or "\n" between)
            if line.startswith("!") or line.startswith("\n"):
                extra_lines.append(line)
                extra_indices.append(i + start_index)
                break
            else:
                break

        else:
            line = line.strip()

            extra_lines.append(line)
            extra_indices.append(i + start_index)

    return extra_indices, extra_lines


def check_global(config_lines, template, compare_method, compare_args):
    template_lines = template.get_content()
    delete_indices = []

    remaining_template_lines = list(template_lines)

    for i, line in enumerate(config_lines):
        line = line.strip()

        if line in template_lines:
            delete_indices.append(i)
            # This will raise an error if a line appears more than x times in the config but only once x-1 times in the template.
            # For example the config has two lines containing a "!" and the template only has one line containing a "!". When we reach
            # the second "!" we wont find it in "remaining_template_lines" since we have deleted it already.
            if line in remaining_template_lines:
                remaining_template_lines.remove(line)

    delete_indices = reversed(sorted(delete_indices))

    for index in delete_indices:
        del config_lines[index]

    return [], remaining_template_lines, config_lines


def load_config(config_path):
    with open(config_path, "r") as config:
        return config.read().splitlines()


def create_template(template_path, context):
    name, raw_content = render_template(template_path, context)

    content_filtered = filter(lambda x: not re.match("^\s*$", x), raw_content.splitlines())
    content_filtered = map(lambda s: s.strip(), content_filtered)

    if not content_filtered:
        raise TemplateError("Content of template is empty, please check your template and parameters")

    return Template(name, content_filtered)


def render_template(template_path, context):
    path, filename = os.path.split(template_path)

    environment = jinja2.Environment(loader=jinja2.FileSystemLoader(path or "./"),
                                     undefined=jinja2.Undefined).get_template(filename)

    return filename, environment.render(context)


def write_results(result_path_expected, result_path_not_expected, log_description, too_much, missing):
    write_expected_config(result_path_expected, log_description, missing)
    write_not_expected_config(result_path_not_expected, log_description, too_much)


def write_expected_config(result_path_expected, log_description, missing):
    if not missing:
        return

    with open(result_path_expected, "a") as result_file:
        if log_description:
            debug_comment = bordered(log_description)
            result_file.write("{}\n".format(debug_comment))

        for line in missing:
            result_file.write("{}\n".format(line))

        result_file.write("\n\n")


def write_not_expected_config(result_path_not_expected, log_description, too_much):
    if not too_much:
        return

    with open(result_path_not_expected, "a") as result_file:
        if log_description:
            debug_comment = bordered(log_description)
            result_file.write("{}\n".format(debug_comment))

        for line in too_much:
            result_file.write("{}\n".format(line))

        result_file.write("\n\n")


def write_remaining_config(config_path, remaining_config):
    if not remaining_config:
        return

    with open(config_path, "w") as result_file:
        for line in remaining_config:
            result_file.write("\n{}".format(line))


def bordered(text):
    width = len(text) + 4

    result = ["!" * width]
    result.append("!" + (" " + text + " ") + "!")
    result.append("!" * width)

    return "\n".join(result)


def main():
    module_args = dict(source=dict(type="str", required=True),
                       destination_expected=dict(type="str", required=False),
                       destination_not_expected=dict(type="str", required=False),
                       template=dict(type="str", required=True),
                       template_args=dict(type="dict", required=False),
                       search_mode=dict(type="str", required=True),
                       search_start=dict(type="str", required=False),
                       search_end=dict(type="str", required=False),
                       compare_method=dict(type="str", required=True),
                       compare_args=dict(type="list", required=False),
                       ignore_lines=dict(type="list", required=False),
                       log_description=dict(type="str", required=False),
                       file_output=dict(type="bool", required=False, default=False),
                       changed_if=dict(type="str", required=False, default="both",
                                       choices=["expected", "not_expected", "both"]))

    # TODO rewrite config

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=False)

    return run_module(module)


if __name__ == "__main__":
    main()
