create view tagged_images as
select
    *,
    (select
        json_agg(tag.name)
    from tag_image
    join tag
        on tag_image.tag = tag.id
    where "image" = "image".id
    ) as tags,
    (select avg(rating) from ratings where "image" = "image".id ) as rating,
    (select count(rating) from ratings where "image" = "image".id ) as rating_count,
    (select max(rating) from ratings where "image" = "image".id ) as rating_top,
    (select max(date) from ratings where "image" = "image".id ) as rating_last_rated
from "image";

create view images_with_tag as
select
    tag.name as tag_name,
    tagged_images.*
from tag_image
join tag on tag.id = tag_image.tag
join tagged_images on tagged_images.id = tag_image.image
where tag is not NULL;

