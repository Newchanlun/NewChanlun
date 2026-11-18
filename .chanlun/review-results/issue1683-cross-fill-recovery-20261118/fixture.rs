
// External acceptance probe; appended only to the exported test source.
#[test]
fn c4b_process_acceptance_forward() {
    let mut s = Session::new("c4b-xproc", true);
    c4b_fills(&mut s);
    let before: Vec<_> = (0..4).map(|i| s.image(i)).collect();
    c4b_book_matches(&s, &json!({"q":[2,5,5],"K":[204,506,506]}));
    let mut cases = Vec::new();
    let raw = c4b_bust_raw("bust-cross-7-2", "8", "net-fill-3", "7", "2", "5");
    let mut refund: Value = serde_json::from_str(C4B_RAW).unwrap();
    let event = &mut refund["events"][8];
    event["depends_on"]["external_fact_id"] = json!("net-fill-1");
    event["netted_fill"]["fill_ref"]["external_fact_id"] = json!("net-fill-1");
    event["netted_fill"]["fill_ref"]["allocation_id"] = json!("alloc-net-fill-1");
    for (input, idx, expected) in [(raw,7,json!({"q":[1,3,3],"K":[102,304,303]})),
        (canonical_json(&refund),8,json!({"q":[1,3,3],"K":[102,302,302]}))] {
        let r = s.capture(&input, idx);
        assert_eq!(r["kind"], "Recorded", "{r}");
        let resolve = s.resolve(&r, idx+1);
        assert_eq!(resolve["kind"],"Resolved","{resolve}");
        let a = s.allocations(&r);
        if idx==7 {
            assert_eq!(c4b_column(&a,"units"),[-1,-2,-2]);
            assert_eq!(c4b_column(&a,"acquisition_cash"),[102,202,203]);
            assert_eq!(c4b_column(&a,"commission"),[0,0,0]);
        } else {
            assert_eq!(c4b_column(&a,"units"),[0,0,0]);
            assert_eq!(c4b_column(&a,"commission"),[0,2,1]);
        }
        let applied = c4b_apply_all(&mut s,&r);
        c4b_book_matches(&s,&expected);
        cases.push(json!({"input":input,"idx":idx,"capture":r,"resolve":resolve,"allocations":a,"applied":applied}));
    }
    let after: Vec<_> = (0..4).map(|i| s.image(i)).collect();
    for key in ["fill_allocations","recorded"] {
        let orig = before[0][key].as_array().unwrap();
        assert_eq!(&after[0][key].as_array().unwrap()[..orig.len()],orig);
    }
    for i in 1..4 {
        let orig = before[i]["applied"].as_array().unwrap();
        assert_eq!(orig.len(),4);
        assert_eq!(&after[i]["applied"].as_array().unwrap()[..orig.len()],orig);
    }
    for i in 0..4 { store::audit(&s.dbs[i],&s.configs[i]).unwrap(); }
    let work = std::path::PathBuf::from(std::env::var_os("C4B_ACCEPT_OUT").unwrap());
    let space = s._space.0.clone();
    std::fs::write(work.join("db-path"),space.to_str().unwrap()).unwrap();
    std::fs::write(work.join("forward.json"),canonical_json(&json!({
        "pid":std::process::id(),"next":s.next,"epochs":s.epochs,"before":before,"after":after,"cases":cases
    }))).unwrap();
    let Session { _space, dbs, .. } = s;
    drop(dbs);
    std::mem::forget(_space);
    println!("FORWARD pid={} db={} original_fees={}", std::process::id(),space.display(),
        canonical_json(&json!(before[0]["fill_allocations"].as_array().unwrap().iter().map(|row|
            c4b_column(row["allocations"].as_array().unwrap(),"commission")).collect::<Vec<_>>())));
}

#[test]
fn c4b_process_acceptance_recover() {
    let work = std::path::PathBuf::from(std::env::var_os("C4B_ACCEPT_OUT").unwrap());
    let space = Space(std::path::PathBuf::from(std::fs::read_to_string(work.join("db-path")).unwrap()));
    let forward: Value = serde_json::from_slice(&std::fs::read(work.join("forward.json")).unwrap()).unwrap();
    assert_ne!(forward["pid"],json!(std::process::id()));
    let path = space.0.join("manifest.json");
    let mut configs = vec![store::Config::load(&path, &space.0.join("e.db"), None).unwrap()];
    for i in 0..3 {
        configs.push(store::Config::load(&path,&space.0.join(format!("b{i}.db")),Some(&format!("chong-N{}",i+1))).unwrap());
    }
    let mut epochs = vec![];
    let mut dbs = vec![];
    for (i,c) in configs.iter().enumerate() {
        let size = std::fs::metadata(&c.db).unwrap().len();
        assert!(size>0);
        let recovered = store::recover(c).unwrap();
        assert_eq!(recovered["kind"],"Recovered");
        let epoch = book::integer(&recovered,"writer_epoch").unwrap();
        assert_eq!(epoch,forward["epochs"][i].as_i64().unwrap()+1);
        println!("RECOVER pid={} db={} bytes={size} epoch={epoch}",std::process::id(),c.db.display());
        epochs.push(epoch);
        dbs.push(store::open(&c.db,false).unwrap().0);
    }
    let mut s = Session {_space:space,configs,dbs,epochs,next:forward["next"].as_u64().unwrap() as usize};
    for i in 0..4 {
        let actual = canonical_json(&s.image(i));
        let expected = canonical_json(&forward["after"][i]);
        assert_eq!(actual.as_bytes(),expected.as_bytes(),"owner {i}: after recover");
        println!("IMAGE owner={i} equal_bytes={}",actual.len());
    }
    for case in forward["cases"].as_array().unwrap() {
        let idx = case["idx"].as_u64().unwrap() as usize;
        let r = s.capture(case["input"].as_str().unwrap(),idx);
        let resolved = s.resolve(&r,idx+1);
        assert_eq!(canonical_json(&r),canonical_json(&case["capture"]));
        assert_eq!(canonical_json(&resolved),canonical_json(&case["resolve"]));
        for i in 1..4 {
            let a = s.send(i,apply_request(&r,&case["allocations"][i-1]["allocation_id"]));
            assert_eq!(canonical_json(&a),canonical_json(&case["applied"][i-1]));
        }
        println!("RECEIPTS case={idx} Capture+Resolve+3 Apply byte-identical");
    }
    for i in 0..4 {
        store::audit(&s.dbs[i],&s.configs[i]).unwrap();
        assert_eq!(canonical_json(&s.image(i)),canonical_json(&forward["after"][i]),"owner {i}: after resends");
    }
    let Session { _space, dbs, .. } = s;
    drop(dbs);
    std::mem::forget(_space);
    println!("RESENDS all four images unchanged; audits passed");
}
