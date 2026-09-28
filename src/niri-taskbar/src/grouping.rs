use std::collections::HashMap;

/// Group only known app IDs. Missing IDs must never collapse unrelated windows.
pub fn groups<'a>(windows: impl Iterator<Item=(u64, Option<&'a str>)>, enabled: bool) -> Vec<Vec<u64>> {
    let mut result: Vec<Vec<u64>> = Vec::new();
    let mut indexes = HashMap::new();
    for (id, app) in windows {
        if enabled && let Some(app) = app.filter(|s| !s.trim().is_empty()) {
            let index = *indexes.entry(app.to_lowercase()).or_insert_with(|| {
                result.push(Vec::new());
                result.len()-1
            });
            result[index].push(id);
        } else { result.push(vec![id]); }
    }
    result
}

pub fn cell(index: usize, rows: u32, vertical: bool) -> (i32, i32) {
    let lanes = rows.clamp(1, 2) as usize;
    let (along, across) = ((index/lanes) as i32, (index%lanes) as i32);
    if vertical { (across, along) } else { (along, across) }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn groups_preserve_order_and_unknown_windows() {
        let data = [(7,Some("firefox")),(8,None),(9,Some("Firefox")),(10,Some("")),(11,None)];
        assert_eq!(groups(data.into_iter(),true),vec![vec![7,9],vec![8],vec![10],vec![11]]);
        assert_eq!(groups(data.into_iter(),false).len(),5);
    }
    #[test]
    fn two_lanes_work_on_each_axis() {
        assert_eq!((cell(0,2,false),cell(1,2,false),cell(2,2,false)),((0,0),(0,1),(1,0)));
        assert_eq!((cell(0,2,true),cell(1,2,true),cell(2,2,true)),((0,0),(1,0),(0,1)));
    }
}

/// Tiled windows follow Niri's column/row order; floating/unknown windows follow.
pub fn tile_order(position: Option<(usize, usize)>, id: u64) -> (bool, usize, usize, u64) {
    let (column, row) = position.unwrap_or((usize::MAX, usize::MAX));
    (position.is_none(), column, row, id)
}

#[cfg(test)]
mod order_tests {
    #[test]
    fn previews_follow_columns_then_rows_not_window_creation() {
        let mut windows = [(1,Some((2,1))), (9,Some((1,2))), (8,Some((1,1))), (2,None)];
        windows.sort_by_key(|(id,position)| super::tile_order(*position,*id));
        assert_eq!(windows.map(|(id,_)|id), [8,9,1,2]);
    }
}
