import re

from ocr.analysis_text.header_values import PersonalInfo, personal_info_patterns, custom_check, table_header_patterns, \
    TableHeaders, remove_text_patterns


class ProcessOutputText(object):
    def __init__(self,word_array):
        self.word_array = word_array
        self.personal_info_raw_data=[]
        self.table_headers=[]
        self.table_data={}
        self.personal_info_data={}

    def find_personal_info(self):
        for word in self.word_array:
            for header_pattern in personal_info_patterns:
                if re.search(header_pattern,word.detected_text):
                    word.header_type=personal_info_patterns[header_pattern]
                    self.personal_info_raw_data.append(word)

    def process_personal_info(self):
        tuning_x=150
        tuning_y=10
        for word in self.word_array:
            for personal_info in self.personal_info_raw_data:
                if (personal_info.get_tr().x + tuning_x > word.get_tl().x >  personal_info.get_tr().x and
                        personal_info.get_tr().y + tuning_y > word.get_tl().y > personal_info.get_tr().y-tuning_y):
                    if custom_check.get(personal_info.header_type):
                        if not( custom_check.get(personal_info.header_type) and custom_check.get(personal_info.header_type)(word.detected_text)):
                            print(word.detected_text)
                            continue
                    if self.personal_info_data.get(personal_info.header_type):
                        self.personal_info_data[personal_info.header_type].append(word)
                    else:
                        self.personal_info_data[personal_info.header_type] = [word]

    def find_table_headers(self):
        for word in self.word_array:
            for table_header_pattern in table_header_patterns:
                if re.search(table_header_pattern,word.detected_text):
                    word.header_type=table_header_patterns[table_header_pattern]
                    self.table_headers.append(word)
    def process_table_headers(self):
        tuning_x = 30
        for word in self.word_array:
            for table_header in self.table_headers:
                if table_header.get_tl().x-tuning_x <= word.get_tl().x <= table_header.get_tr().x + tuning_x and word.get_tl().y>table_header.get_tl().y:
                    if custom_check.get(table_header.header_type):
                        if not custom_check.get(table_header.header_type)(
                            word.detected_text):
                            continue
                    if self.table_data.get(table_header.header_type):
                        word.header_type=table_header.header_type
                        self.table_data[table_header.header_type].append(word)
                    else:
                        self.table_data[table_header.header_type] = [word]

    def analyze_row(self,key,column):
        row={key}
        tuning_y=15
        for col in self.table_data:
            if column == col:
                continue
            for word in self.table_data[col]:
                if key.get_tl().y+tuning_y>=word.get_tl().y>=key.get_tl().y-tuning_y:
                    row.add(word)

        row=list(row)
        row.sort()
        return row
    def process_table_data(self):
        rows=[]
        for column in self.table_data:
            for word in self.table_data[column]:
                row=self.analyze_row(word,column)
                if len(row)>1:
                    rows.append(row)

        return rows

    def process_missing_items(self,rows):
        tuning_y=15
        print(len(self.word_array))
        for word in self.word_array:
            for row in rows:
                if row[0].get_tl().y+tuning_y>=word.get_tl().y>=row[0].get_tl().y - tuning_y:

                    if word not in row and not [i for i in remove_text_patterns if  re.match(i,word.detected_text)]:
                        row.append(word)
                        row.sort()
        for row in rows:
            if word in row:
                word
        return rows

    def remove_duplicate(self,data):
        new_data = []
        for row in data:
            if row not in new_data:
                new_data.append(row)
        return new_data





if __name__ == '__main__':
    ProcessOutputText([]).find_header_text()