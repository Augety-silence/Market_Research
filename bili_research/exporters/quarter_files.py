"""CSV和原生Excel公式、独立折线图导出。"""
import csv
from pathlib import Path
from ..collectors.quarter_search import HEADERS, PROGRESS_HEADERS


def export_csv(store, directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    for name,header,rows in [('视频明细.csv',HEADERS,store.rows()),('断点进度.csv',PROGRESS_HEADERS,store.progress())]:
        tmp=directory/(name+'.tmp')
        with tmp.open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f);writer.writerow(header);writer.writerows(rows)
        tmp.replace(directory/name)


def export_xlsx(store, config, path):
    from openpyxl import Workbook
    from openpyxl.chart import LineChart, Reference
    from openpyxl.styles import Alignment, Font, PatternFill
    book=Workbook();detail=book.active;detail.title='视频明细'
    detail.append(HEADERS)
    for row in store.rows():
        detail.append(row)
        for col in (1,2,3,4,5,7,9):
            # 避免标题被Excel当作公式。
            detail.cell(detail.max_row,col).data_type='s'
    detail.freeze_panes='B2';detail.auto_filter.ref=detail.dimensions
    progress=book.create_sheet('断点进度');progress.append(PROGRESS_HEADERS)
    for row in store.progress():progress.append(row)
    progress.freeze_panes='B2'
    summary=book.create_sheet('季度汇总');drugs=config['keywords'];quarters=sorted({j['quarter'] for j in store.jobs()})
    summary.append(['季度']+[label for drug in drugs for label in (drug+'累计播放量',drug+'BV数')])
    # 本地Excel用完整明细范围，避免重算时扫描整列过慢。
    end=max(2,detail.max_row)
    for n,q in enumerate(quarters,2):
        summary.cell(n,1,q)
        for i,drug in enumerate(drugs):
            summary.cell(n,2+i*2,f'=SUMIFS(\'视频明细\'!$F$2:$F${end},\'视频明细\'!$A$2:$A${end},"{drug.replace(chr(34), chr(34)*2)}",\'视频明细\'!$B$2:$B${end},$A{n})')
            summary.cell(n,3+i*2,f'=COUNTIFS(\'视频明细\'!$A$2:$A${end},"{drug.replace(chr(34), chr(34)*2)}",\'视频明细\'!$B$2:$B${end},$A{n},\'视频明细\'!$C$2:$C${end},"<>")')
    summary.freeze_panes='B2'
    dashboard=book.create_sheet('独立趋势图')
    colors=['2563EB','0D9488','F59E0B']
    for i,drug in enumerate(drugs):
        for metric,col in [('累计播放量',2+i*2),('BV数',3+i*2)]:
            chart=LineChart();chart.title=drug+'｜'+metric+'趋势';chart.y_axis.title=metric;chart.x_axis.title='发布季度'
            chart.width=25;chart.height=11;chart.y_axis.scaling.min=0
            chart.add_data(Reference(summary,min_col=col,min_row=1,max_row=len(quarters)+1),titles_from_data=True)
            chart.set_categories(Reference(summary,min_col=1,min_row=2,max_row=len(quarters)+1))
            chart.series[0].graphicalProperties.line.solidFill=colors[i%3]
            chart.series[0].marker.symbol='circle';chart.series[0].marker.size=5
            dashboard.add_chart(chart,f'A{3+(i*2+(metric=="BV数"))*24}')
    dashboard['A1']='关键词匹配视频累计播放量；按发布日期归属季度，非季度新增播放量。结束季度以配置截止日期为准。'
    for sheet in (detail,progress,summary):
        for cell in sheet[1]:
            cell.fill=PatternFill('solid',fgColor='17365D');cell.font=Font(color='FFFFFF',bold=True)
        for column in sheet.columns:
            letter=column[0].column_letter
            sheet.column_dimensions[letter].width=18 if letter!='D' else 55
        for row in sheet:
            for cell in row:
                cell.alignment=Alignment(vertical='center',wrap_text=True)
        sheet.row_dimensions[1].height=32
    for row in summary.iter_rows(min_row=2,min_col=2):
        for cell in row:cell.number_format='#,##0'
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp.xlsx');book.save(temporary);temporary.replace(path)
    return path
