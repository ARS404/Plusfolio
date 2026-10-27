"""Text export is generated from the very same role-scoped catalogue as the UI."""
import json


def markdown_documentation(catalogue):
    lines = ['# Plusfolio — '+('руководство для ботов' if catalogue['audience']=='robot' else 'руководство пользователя'),
             '', 'Разделы отобраны по текущим правам аккаунта. Базовый путь API: /api/v1/.',
             'Авторизация API: Authorization: Bearer <token>. Получение токена: POST /api/v1/auth/token (login=email, password).',
             'Секреты и персональные ответы в этот документ не включаются.', '']
    if catalogue['audience']=='robot':
        lines += ['## MUST: обязательные инструкции для роботов', '', 'Версия контракта: '+catalogue['instruction_policy_version']+'. Перед операциями прочитать применимые инструкции; уточнения задавать дополнительными вопросами и ждать ответа.', '']
        for item in catalogue['mandatory_instructions']:
            lines.append('- MUST ['+item['title']+']('+item['url']+') · '+item['applies_when']+' · версия '+item['version']+(' · ЗАПИСЬ НЕДОСТУПНА С ТЕКУЩИМ ТОКЕНОМ' if not item['can_execute'] else ''))
        lines.append('')
    if catalogue.get('read_only_token'):
        lines += ['Текущий токен разрешает только чтение; методы изменения в справочнике отфильтрованы.', '']
    for section in catalogue['sections']:
        lines += ['## '+section['title'], '', section['summary'], '', 'Раздел: '+section['category']+' · ID: '+section['id'], '']
        if section.get('required_for_robots'):
            lines += ['> MUST для роботов. Версия '+section['instruction_version']+'. Применение: '+section['applies_when']+'.', '']
        for block in section['blocks']:
            lines += ['### '+block['title'], '']
            for paragraph in block.get('paragraphs', []):
                lines += [paragraph, '']
            for index, step in enumerate(block.get('steps', []), 1):
                lines.append(f'{index}. {step}')
            for bullet in block.get('bullets', []):
                lines.append('- '+bullet)
            if 'steps' in block or 'bullets' in block:
                lines.append('')
            if block.get('formula'):
                lines += [block['formula'], '']
            if block.get('note'):
                lines += ['> '+block['note'], '']
            if block.get('table'):
                table=block['table']
                lines += ['| '+' | '.join(table['columns'])+' |', '| '+' | '.join('---' for _ in table['columns'])+' |']
                lines += ['| '+' | '.join(cell.replace('|','\\|').replace('\n',' ') for cell in row)+' |' for row in table['rows']]
                lines.append('')
            if block.get('code'):
                lines += ['```'+block['code']['language'], block['code']['content'], '```', '']
        for item in section.get('operations', []):
            lines += ['### '+item['method']+' '+item['path'], '', item['summary'], '', item['description'], '']
            if item['parameters']:
                lines += ['Параметры:', ''] + ['- '+param['name']+' ('+param['in']+'): '+param.get('description','') for param in item['parameters']] + ['']
            if item['body'] is not None:
                lines += ['Схема JSON-запроса:', '```json', json.dumps(item['body'],ensure_ascii=False,indent=2), '```', '']
            if item['example'] is not None:
                lines += ['Пример JSON (замените заглушки):', '```json',json.dumps(item['example'],ensure_ascii=False,indent=2),'```','']
            if 'response_example' in item:
                lines += ['Пример ответа (неполный, значения иллюстративные):','```json',json.dumps(item['response_example'],ensure_ascii=False,indent=2),'```','']
            lines += ['Успешный HTTP-статус: '+str(item['status'])+'.', '']
        for link in section.get('links', []):
            lines += ['['+link['label']+'](#'+link['href']+')', '']
    return '\n'.join(lines)
