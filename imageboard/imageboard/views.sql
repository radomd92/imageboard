create view tagged_image as
select
    *,
    (select json_agg(tag.name) from tag where "image" = "image".id ) as tags,
    (select avg(rating) from ratings where "image" = "image".id ) as rating,
    (select count(rating) from ratings where "image" = "image".id ) as rating_count,
    (select max(rating) from ratings where "image" = "image".id ) as rating_top,
    (select max(date) from ratings where "image" = "image".id ) as rating_last_rated
from "image";

