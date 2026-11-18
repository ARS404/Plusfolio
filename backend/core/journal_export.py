"""Downloadable journal snapshots. User text is always written as literal text."""
import csv
import fcntl
import io
import tempfile
import re
from datetime import datetime
from pathlib import Path
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework.exceptions import Throttled
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.worksheet._writer import ALL_TEMP_FILES,WorksheetWriter
from . import services as s
from .journal import select_issues,snapshot,view_options
from .tex_runtime import job_directory

FILE_FORMATS = {'xlsx', 'tsv'}
MAX_XLSX_COLUMNS = 16_384
MAX_EXPORT_CELLS = 1_000_000

GREEN = '365B4A'
PALE = 'EAF1E3'
BLUE = 'EAF0F3'
ILLEGAL_XML = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def columns(data):
    result = []
    for index, block in enumerate(data['blocks']):
        for number, problem in enumerate(block['problems'], 1):
            position=problem.get('worksheet_position',number)
            result.append((index, block, problem, f'№{position} · {problem["title"]}'))
        if data['show_group_stats']:
            result.append((index, block, None, 'Решено'))
    return result


def rows(data, cols):
    states = {(state['student_id'], state['problem_id']) for state in data['solves'] if state['solved']}
    discussed = {state['problem_id']: state['discussed'] for state in data['discussions']}
    yield ['Разобрана в кружке'] + [('Да' if discussed.get(problem['id'], False) else 'Нет') if problem else '' for _, _, problem, _ in cols]
    for person in data['people']:
        row = [person['name']]
        solved_count = 0
        for _, block, problem, _ in cols:
            if not block['visible_to_students']:
                row.append('—')
            elif problem:
                solved = (person['id'], problem['id']) in states
                solved_count += solved
                row.append('Да' if solved else 'Нет')
            else:
                row.append(solved_count)
                solved_count = 0
        yield row


def block_title(block, date):
    title=block['worksheet']['title']
    status='' if block['visible_to_students'] else ' · Скрыт от школьников'
    return f'{title} · {date}{status}'


def text(value):
    return ILLEGAL_XML.sub('', str(value))[:32767]


def tsv_cell(value):
    value = text(value)
    # Spreadsheet applications can execute formula-looking text on opening TSV.
    if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
        value = "'" + value
    return value


def xlsx(data, cols, directory=None):
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet('Журнал')
    sheet.sheet_view.showGridLines = False
    width = 1 + len(cols)
    body_font = Font(name='Calibri', size=11, color='273E34')
    block_font = Font(name='Calibri', size=11, bold=True, color=GREEN)
    task_font = Font(name='Calibri', size=10, bold=True, color=GREEN)
    left = Alignment(vertical='center', horizontal='left', wrap_text=True)
    centered = Alignment(vertical='center', horizontal='center', wrap_text=True)
    block_fills = (PatternFill('solid', fgColor=PALE), PatternFill('solid', fgColor=BLUE))
    discussion_fill = PatternFill('solid', fgColor='F0F3ED')
    solved_fill = PatternFill('solid', fgColor='E7F0DF')
    stripe_fill = PatternFill('solid', fgColor='FAFBF8')
    bottom_border = Border(bottom=Side(style='hair', color='DFE6DB'))

    def cell(value, column):
        item = WriteOnlyCell(sheet)
        if isinstance(value, (int, float)):
            item.value = value
        else:
            item.value = text(value)
            item.data_type = 's'
        item.font = body_font
        item.alignment = centered if column > 1 else left
        return item

    def title_row(row, value):
        if width > 1:
            sheet.merged_cells.add(f'A{row}:{get_column_letter(width)}{row}')
        item = cell(value, 1)
        if row == 1:
            item.font = Font(name='Calibri', size=18, bold=True, color=GREEN)
        sheet.append([item])

    sheet.column_dimensions['A'].width = 30
    for column, (_, _, problem, _) in enumerate(cols, 2):
        sheet.column_dimensions[get_column_letter(column)].width = 19 if problem else 12
    sheet.row_dimensions[1].height = 32
    sheet.row_dimensions[2].height = 25
    sheet.row_dimensions[3].height = 30
    sheet.row_dimensions[5].height = 42
    sheet.row_dimensions[6].height = max(64, min(160, max((len(label) // 18 + 1) * 12 for *_, label in cols))) if cols else 40
    sheet.freeze_panes = 'B7'
    sheet.print_title_rows = '1:7'
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = Worksheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 0
    sheet.page_setup.fitToHeight = 0
    try:
        if directory is not None:
            # openpyxl registers named XML files for cleanup. Keep the spool in
            # the leased job directory, including when a worker is interrupted.
            spool=str(directory/'worksheet.xml')
            sheet._writer=WorksheetWriter(sheet,out=spool)
            ALL_TEMP_FILES.append(spool)
            sheet._writer.write_top()
        title_row(1, f'Plusfolio · {data["circle"]["name"]}')
        title_row(2, f'Журнал сдачи · Снимок на {timezone.localtime():%d.%m.%Y %H:%M} · Листков: {len(data["blocks"])} · Школьников: {len(data["people"])}')
        title_row(3, 'Да / Нет — задача решена. Решённость общая между кружками; разбор относится к этому кружку.')
        sheet.append([])
        header = [cell('', column) for column in range(1, width + 1)]
        header[0].value = 'Школьник'
        header[0].fill = PatternFill('solid', fgColor=GREEN)
        header[0].font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        sheet.merged_cells.add('A5:A6')
        start = 2
        for index, block in enumerate(data['blocks']):
            count = len(block['problems']) + int(data['show_group_stats'])
            if not count:
                continue
            issued_on = datetime.fromisoformat(block['issued_on']).strftime('%d.%m.%Y')
            header[start - 1].value = text(block_title(block, issued_on))
            header[start - 1].data_type = 's'
            if count > 1:
                sheet.merged_cells.add(f'{get_column_letter(start)}5:{get_column_letter(start + count - 1)}5')
            for column in range(start, start + count):
                item = header[column - 1]
                item.fill = block_fills[index % 2]
                item.font = block_font
                item.alignment = centered
            start += count
        sheet.append(header)
        labels = [cell('', 1)]
        for column, (index, _, _, label) in enumerate(cols, 2):
            item = cell(label, column)
            item.fill = block_fills[index % 2]
            item.font = task_font
            labels.append(item)
        sheet.append(labels)
        for row_number, values in enumerate(rows(data, cols), 7):
            sheet.row_dimensions[row_number].height = 28
            output = []
            for column, value in enumerate(values, 1):
                item = cell(value, column)
                if row_number == 7:
                    item.fill = discussion_fill
                elif column > 1 and value == 'Да':
                    item.fill = solved_fill
                elif row_number % 2 == 0:
                    item.fill = stripe_fill
                item.border = bottom_border
                output.append(item)
            sheet.append(output)
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()
    finally:
        try:
            if not sheet.closed:
                sheet.close()
        finally:
            # openpyxl normally removes its spool on save. Also remove it when
            # writing fails, so long-lived web workers cannot accumulate files.
            writer = sheet._writer
            if writer is not None and Path(writer.out).exists():
                writer.cleanup()
            workbook.close()


def check_size(width,students):
    if width>MAX_XLSX_COLUMNS or (students+8)*width>MAX_EXPORT_CELLS:
        raise ValidationError('Выгрузка слишком большая. Выберите меньше листков или уточните поиск школьника.')


def export(user, circle, params):
    file_format=params.get('file_format','xlsx')
    if file_format not in FILE_FORMATS:
        raise ValidationError('Доступны форматы Excel (.xlsx) и TSV (.tsv).')
    options=view_options(params)
    directory=Path(tempfile.gettempdir())/'plusfolio-journal-exports'
    directory.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (directory/'.lock').open('a') as lease:
        try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Throttled(wait=5,detail='Выгрузка журнала занята. Повторите через несколько секунд.')
        with job_directory(directory) as work:
            selected=select_issues(s.issues_for(user).filter(circle=circle),params.get('issues','all'),for_export=True,hide_discussed=options['hide_discussed'])
            data=snapshot(user,circle,selected,lambda problem,user:{'id':str(problem.pk),'title':problem.display_title},
                          params.get('q',''),export_options=options)
            cols=columns(data)
            if file_format=='xlsx':
                body=xlsx(data,cols,work)
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            else:
                buffer=io.BytesIO()
                with io.TextIOWrapper(buffer,encoding='utf-8-sig',newline='') as stream:
                    writer=csv.writer(stream,delimiter='\t',lineterminator='\r\n')
                    writer.writerow(['Школьник']+[tsv_cell(block_title(block,block['issued_on'])) for _,block,_,_ in cols])
                    writer.writerow(['']+[tsv_cell(label) for _,_,_,label in cols])
                    writer.writerows([tsv_cell(value) for value in row] for row in rows(data,cols))
                    stream.flush()
                    body=buffer.getvalue()
                content_type='text/tab-separated-values; charset=utf-8'
    response=HttpResponse(body,content_type=content_type)
    filename=f'plusfolio-{data["circle"]["id"][:8]}-{timezone.localdate():%Y%m%d}.{file_format}'
    response['Content-Disposition']=content_disposition_header(True,filename)
    response['Cache-Control']='no-store'
    return response
