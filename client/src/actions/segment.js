export const UPDATE_SEGMENT = 'UPDATE_SEGMENT';
export const FOCUS_SEGMENT = 'FOCUS_SEGMENT';
export const UPDATE_MODIFIED = 'UPDATE_MODIFIED';

export const updateSegment = (segmentId, field, value) => dispatch => {
  dispatch({
    type: UPDATE_SEGMENT,
    segmentId,
    dataType: field,
    value
  })
}

export const focusSegment = segmentId => dispatch => {
  dispatch({
    type: FOCUS_SEGMENT,
    segmentId
  })
}


export const updateModified = (key, modified) => dispatch => {
  dispatch({type: UPDATE_MODIFIED, key, modified})
}