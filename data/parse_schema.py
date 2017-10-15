import argparse
from collections import namedtuple
import re
import pytz, datetime
import logging
logging.basicConfig()
logger = logging.getLogger(__name__)


TITLE_ID = 'title:'
INSTRUCTIONS_ID = 'instructions:'
GLOSSARY_ID = 'glossary:'
DEPENDENCY_ID = 'if'
DEPENDENCY_TARGET = 'then'
VERSION_ID = 'version:'
VERSION_NUM = '3'

QUESTION_TYPES = {'mc' : 'RADIO',
                  'cl' : 'CHECKBOX',
                  'tx' : 'TEXT',
                  'dt' : 'DATE',
                  'tm' : 'TIME',
                  'st' : 'SUBTOPIC'}

Dependency = namedtuple('Dependency',
    ['topic', 'question', 'answer', 'next_question', 'next_topic'])

class SimpleParseException(Exception):
    pass

class ParseSchemaException(Exception):

    def __init__(self, message, file_name, linenum, *args):
        super(ParseSchemaException, self).__init__(message, file_name,
                                                   linenum, *args)
        self.message = message
        self.errtype = 'ParseSchemaException'
        self.file_name = file_name
        self.linenum = linenum
        self.timestamp = datetime.datetime.now(pytz.utc)
    def log(self):
        logger.error("In line {} of file {}, {} error: {}, at {:%Y-%m-%d %H:%M:%S %Z}"
                     .format(self.linenum, self.file_name, self.errtype, self.message,
                             self.timestamp))

def load_defaults(output):
    output['topics'] = []
    output['dependencies'] = []

def parse_schema(schema_file):
    parsed_schema = {}
    load_defaults(parsed_schema)
    with open(schema_file, 'r') as f:
        linecount = 1
        version = ''
        first_line = True
        current_topic = None
        for line in f:
            raw_line = line.strip()

            if '#' in raw_line:
                hashsplit = raw_line.split("#")

                single = hashsplit[0].count('\'')
                smart_single = hashsplit[0].count('\xe2\x80\x98') + hashsplit[0].count('\xe2\x80\x99')
                escaped_single = hashsplit[0].count('\\\'')

                double = hashsplit[0].count('\"')
                smart_double = hashsplit[0].count('\xe2\x80\x9c') + hashsplit[0].count('\xe2\x80\x9d')

                escaped_double = hashsplit[0].count('\\\"')
                if (single + smart_single - escaped_single) % 2 == 0 and (double + smart_double - escaped_double) % 2 == 0:
                    raw_line = hashsplit[0]

            raw_line = raw_line.strip()

            # Throw out blank lines
            if not raw_line:
                linecount += 1
                continue

            try:
                # Infer the line type and parse accordingly
                type_id, data = raw_line.split(None, 1)
                if type_id.lower() == VERSION_ID and first_line:
                    version = data.strip()
                    first_line = False
                    if version != '3':
                        msg = ("'version: 3' must be first non-blank line. "
                              "Found '{}'".format(raw_line))
                        raise ParseSchemaException(msg, schema_file, linecount)
                elif first_line:
                    msg = ("'version: 3' must be first non-blank line. "
                          "Found '{}'".format(type_id))
                    raise ParseSchemaException(msg, schema_file, linecount)
                elif type_id.lower() == TITLE_ID:
                    current_topic = parse_title(data, parsed_schema)
                elif type_id.lower() == INSTRUCTIONS_ID:
                    parse_instructions(data, current_topic)
                elif type_id.lower() == GLOSSARY_ID:
                    parse_glossary(data, current_topic)
                elif type_id.lower() == DEPENDENCY_ID:
                    parse_dependency(data, parsed_schema)
                elif type_id[0].isdigit():
                    topic_id = parse_question_entry(type_id, data, current_topic)
                    if current_topic['id'] is None:
                        current_topic['id'] = topic_id
                else:
                    # type_id is wrong or split lines returned wrong stuff
                    msg = "Invalid type_id {}".format(type_id)
                    raise ParseSchemaException(msg, schema_file, linecount)
            except SimpleParseException as e:
                raise ParseSchemaException(e.message, schema_file, linecount)
            except ValueError as e:
                # split will raise a ValueError if it can't find a split point
                # so let's tell the researcher what line of the schema caused
                # that instead of a stacktrace.
                raise ParseSchemaException(e.message, schema_file, linecount)

            linecount += 1

    return parsed_schema

def parse_title(title, output):
    # id will be set by next question encountered
    current_topic = {
        'id': None,
        'name': title,
        'questions': [],
        'glossary': {},
        'instructions': '',
    }
    output['topics'].append(current_topic)
    return current_topic

def parse_instructions(instructions, current_topic):
    current_topic['instructions'] = instructions

def parse_glossary(glossary_entry, current_topic):
    term, definition = glossary_entry.split(':', 1)
    current_topic['glossary'][term.strip()] = definition.strip()

def parse_dependency(dependency, output):

    # Parsing two formats:
    # if t.q.a, then t
    # if t.q.a, then t.q
    # t is a topic number
    # q is a question number
    # a can be an answer number or 'any'

    splitted_dependency = dependency.split(', ')
    source_phrase = splitted_dependency[0]
    target_phrase = splitted_dependency[1].split(' ')[1]
    source_topic_id, source_question_id, source_answer_id = (
        source_phrase.split('.'))
    target_dependency = target_phrase.split('.')
    # -1 if there is no target_question.
    target_question = target_dependency[1] if len(target_dependency) > 1 else -1
    target_topic = target_dependency[0]

    source_topic_id = int(source_topic_id)
    source_question_id = int(source_question_id)
    target_question = int(target_question)
    target_topic = int(target_topic)

    # Do not convert source_answer_id to int, because value might be 'any'
    # source_answer_id = int(source_answer_id)
    output['dependencies'].append(Dependency(source_topic_id,
                                             source_question_id,
                                             source_answer_id,
                                             target_question,
                                             target_topic))

def infer_hint_type(question):
    match = re.search("WHERE|WHO|HOW MANY|WHEN", question, re.IGNORECASE)
    if match:
        return match.group(0).upper()
    else:
        return 'NONE';

def parse_question_entry(entry_id, data, current_topic):
    type_bits = entry_id.split('.')
    num_bits = len(type_bits)
    if num_bits == 2:
        topic_id, question_id = type_bits
        question_id = type_bits[1]
        question_type, question_text = data.split(None, 1)
        hint_type = infer_hint_type(question_text)
        if question_type in QUESTION_TYPES:
            question_type = QUESTION_TYPES[question_type]
        current_topic['questions'].append({
            'question_number': question_id,
            'question_text': question_text,
            'question_type': question_type,
            'answers': [],
            'hint_type': hint_type,

        })
    elif num_bits == 3:
        topic_id, question_id, answer_id = type_bits
        question = [q for q in current_topic['questions'] if q['question_number'] == question_id][0]
        question['answers'].append({
            'answer_number': answer_id,
            'answer_content': data,
        })
    else:
        raise SimpleParseException(
            "Expected topic.question or topic.question.answer. Found '{}'"
            .format(entry_id)
        )
    return topic_id

def print_data(output):
    import pprint; pprint.pprint(output)

def print_dependencies(output):
    import pprint; pprint.pprint(output['dependencies'])

if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('filename', nargs=1)
    args = arg_parser.parse_args()

    try:
        output = parse_schema(args.filename[0])
        print_data(output)
        # print_dependencies(output)
    except ParseSchemaException as e:
        e.log()
