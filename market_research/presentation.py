"""PDF逐页转为纯图片PPT；不需要Office或Aime浏览器。"""
from io import BytesIO
from pathlib import Path

def pdf_to_ppt(source,output,dpi=240):
    import fitz
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    if dpi<72 or dpi>600: raise ValueError('dpi须在72..600之间')
    with fitz.open(source) as doc:
        if not len(doc): raise ValueError('PDF没有页面')
        prs=Presentation();first=doc[0].rect;prs.slide_width=round(first.width*12700);prs.slide_height=round(first.height*12700)
        for page in doc:
            if abs(page.rect.width-first.width)>.01 or abs(page.rect.height-first.height)>.01:
                raise ValueError('PDF页面尺寸不同，须先统一页面比例')
            pix=page.get_pixmap(dpi=dpi,colorspace=fitz.csRGB,alpha=False)
            slide=prs.slides.add_slide(prs.slide_layouts[6]);slide.shapes.add_picture(BytesIO(pix.tobytes('png')),0,0,width=prs.slide_width,height=prs.slide_height)
        Path(output).parent.mkdir(parents=True,exist_ok=True);prs.save(output)
    check=Presentation(output)
    if any(len(s.shapes)!=1 or s.shapes[0].shape_type!=MSO_SHAPE_TYPE.PICTURE for s in check.slides):
        raise RuntimeError('导出校验失败：每页必须只有一张整页图片')
    return len(check.slides)
