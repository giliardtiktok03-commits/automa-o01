"""Explicit subtitle styling and layout, independent of material generation."""
FIELDS = ('subtitle_enabled','font_name','font_size','text_fore_color','stroke_color','stroke_width',
          'subtitle_position','subtitle_display_mode','subtitle_animation','text_background_color',
          'rounded_subtitle_background','subtitle_soft_shadow','subtitle_max_lines')
DOCUMENTARY = dict(subtitle_enabled=True,font_name='Montserrat-ExtraBold.ttf',font_size=60,
                   text_fore_color='#FFFFFF',stroke_color='#000000',stroke_width=4.0,
                   subtitle_position='bottom',subtitle_display_mode='sentence',subtitle_animation='none',
                   text_background_color=False,rounded_subtitle_background=False,
                   subtitle_soft_shadow=True,subtitle_max_lines=2)


def apply(params, settings):
    from app.models.schema import VideoParams
    values={key:settings[key] for key in FIELDS if key in settings}
    return VideoParams.model_validate({**params.model_dump(mode='json'),**values})


def limit_lines(cues, max_lines, wrap):
    """Split long cues within their original interval; never change the SRT/audio."""
    if not max_lines:
        return cues
    result=[]
    for (start,end),text in cues:
        lines=wrap(text).split('\n')
        chunks=['\n'.join(lines[i:i+max_lines]) for i in range(0,len(lines),max_lines)]
        weights=[max(1,len(chunk)) for chunk in chunks]
        total=sum(weights)
        elapsed=0
        for chunk,weight in zip(chunks,weights):
            left=start+(end-start)*elapsed/total
            elapsed+=weight
            right=start+(end-start)*elapsed/total
            result.append(((left,right),chunk))
    return result
